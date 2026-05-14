//! Software rendering: softbuffer pixel buffer + ab_glyph direct rasterization.
//!
//! Replaces the previous cosmic-text Buffer-per-cell approach.  ab_glyph goes
//! straight to the glyph rasterizer (no layout engine), which gives pixel-perfect
//! monospace advance widths for Commit Mono without any cosmic-text layout padding.

use ab_glyph::{Font as _, FontArc, FontRef, PxScale, ScaleFont as _};

use crate::error::{AppError, AppResult};
use crate::native_term::grid::{Cell, Color, Grid};

/// Bundled Commit Mono OTF — embedded at compile time.
const COMMIT_MONO_400: &[u8] = include_bytes!(
    "../../../src/assets/fonts/CommitMono-400-Regular.otf"
);

/// Bundled JetBrains Mono — used as the FIRST fallback because its block
/// elements (U+2580–U+259F) and box-drawing glyphs (U+2500–U+257F) are
/// drawn to fill the cell exactly, which TUI apps like OpenCode and Claude
/// Code rely on for their banner art and input borders.  Commit Mono lacks
/// these or draws them with gaps.
const JETBRAINS_MONO: &[u8] = include_bytes!(
    "../../../src/assets/fonts/JetBrainsMono-Regular.ttf"
);

/// Candidate paths for fallback fonts that cover the Unicode glyphs Commit
/// Mono lacks.  We probe them all at startup and load every one that exists,
/// then try each per-glyph in order until one provides a non-`.notdef`
/// glyph for the requested character.
///
/// Why multiple: DejaVu Sans Mono covers box-drawing + braille but lacks
/// U+23F5 ⏵ (Claude Code's "bypass permissions" arrow) and other geometric
/// glyphs.  Noto Sans Symbols2 covers the geometric block but lacks some of
/// DejaVu's Latin extensions.  Combining gives near-complete coverage.
const FALLBACK_FONT_CANDIDATES: &[&str] = &[
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
];

fn load_fallback_fonts() -> Vec<FontArc> {
    use std::sync::OnceLock;
    static CACHE: OnceLock<Vec<FontArc>> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            let mut fonts = Vec::new();
            // JetBrains Mono is bundled (always available) — block elements,
            // box-drawing, and braille all draw to fill the cell properly.
            if let Ok(font) = FontArc::try_from_vec(JETBRAINS_MONO.to_vec()) {
                eprintln!("[native-term] fallback font loaded: bundled JetBrains Mono");
                fonts.push(font);
            }
            for path in FALLBACK_FONT_CANDIDATES {
                if let Ok(bytes) = std::fs::read(path) {
                    if let Ok(font) = FontArc::try_from_vec(bytes) {
                        eprintln!("[native-term] fallback font loaded: {path}");
                        fonts.push(font);
                    }
                }
            }
            if fonts.is_empty() {
                eprintln!(
                    "[native-term] no fallback fonts found — non-ASCII glyphs may be missing"
                );
            }
            fonts
        })
        .clone()
}

/// Inner padding (px) — gives the terminal text room to breathe.
pub const PADDING_X: u32 = 14;
pub const PADDING_Y: u32 = 10;

// ---------------------------------------------------------------------------
// FontStack
// ---------------------------------------------------------------------------

pub struct FontStack {
    /// Parsed primary face (zero-copy borrow of the static Commit Mono slice).
    pub face: FontRef<'static>,
    /// Ordered fallback chain.  draw_glyph tries each per-glyph until one
    /// provides a non-`.notdef` shape.
    pub fallbacks: Vec<FontArc>,
    /// Pixel scale derived from the requested point size.
    pub scale: PxScale,
    /// Ascent in pixels at the current scale (baseline offset from cell top).
    pub ascent: f32,
}

impl FontStack {
    pub fn new(font_size: f32) -> Self {
        let face =
            FontRef::try_from_slice(COMMIT_MONO_400).expect("Commit Mono embedded bytes valid");
        let scale = PxScale::from(font_size * 4.0 / 3.0);
        let scaled = face.as_scaled(scale);
        let ascent = scaled.ascent();
        let fallbacks = load_fallback_fonts();
        Self { face, fallbacks, scale, ascent }
    }

    /// Horizontal advance (cell width) in whole pixels — h_advance for 'M'.
    pub fn advance(&self) -> u32 {
        let scaled = self.face.as_scaled(self.scale);
        scaled.h_advance(self.face.glyph_id('M')).ceil() as u32
    }

    /// Line height in whole pixels: (ascent − descent + line_gap) × 1.15
    /// for a slightly relaxed terminal look (Commit Mono's natural metrics
    /// pack lines too tight for a TUI).
    pub fn line_height(&self) -> u32 {
        let scaled = self.face.as_scaled(self.scale);
        let natural = scaled.ascent() - scaled.descent() + scaled.line_gap();
        (natural * 1.15).ceil() as u32
    }
}

// ---------------------------------------------------------------------------
// Measure helper (public — used by commands.rs)
// ---------------------------------------------------------------------------

/// Return `(cell_width_px, line_height_px)` for a monospace font at `font_size`
/// (points, 96 DPI).  No FontSystem needed — pure ab_glyph metrics.
pub fn measure_cell(font_size: f32) -> (u32, u32) {
    let stack = FontStack::new(font_size);
    let w = stack.advance();
    let h = stack.line_height();
    eprintln!("[native-term] measure_cell w={w} h={h}");
    (w.max(1), h.max(1))
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

#[allow(dead_code)] // populated by attach
pub struct Renderer {
    pub width: u32,
    pub height: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub buffer: Vec<u32>,
    pub fonts: FontStack,
}

#[allow(dead_code)] // wired up in attach
impl Renderer {
    pub fn new(
        width: u32,
        height: u32,
        cell_w: u32,
        cell_h: u32,
        font_size: f32,
    ) -> AppResult<Self> {
        if width == 0 || height == 0 {
            return Err(AppError::Terminal("renderer: zero-dim surface".into()));
        }
        Ok(Self {
            width,
            height,
            cell_w,
            cell_h,
            buffer: vec![0u32; (width * height) as usize],
            fonts: FontStack::new(font_size),
        })
    }

    pub fn fill_background(&mut self, bg: Color) {
        let pixel = pack_color(bg);
        self.buffer.iter_mut().for_each(|p| *p = pixel);
    }

    pub fn render_grid(&mut self, grid: &Grid, cursor_visible: bool) {
        self.fill_background(Color::black());
        // Pre-compute normalised selection so each cell can check membership.
        let sel_norm = grid.selection.map(crate::native_term::grid::normalize_selection);
        for r in 0..grid.rows {
            for c in 0..grid.cols {
                let cell = grid.cell_at(r, c);
                let in_selection = match sel_norm {
                    Some(((r0, c0), (r1, c1))) => cell_in_range(r, c, r0, c0, r1, c1, grid.cols),
                    None => false,
                };
                if in_selection {
                    // Translucent cyan tint over selection.
                    self.fill_cell_bg(r, c, Color::rgb(0x12, 0x4a, 0x57));
                } else if cell.bg != Color::black() {
                    self.fill_cell_bg(r, c, cell.bg);
                }
                if cell.ch != ' ' {
                    self.draw_glyph(r, c, cell);
                }
            }
        }
        if cursor_visible {
            self.draw_cursor(grid);
        }
    }

    /// Solid block cursor rendered as inverse-video over the cell at
    /// `(grid.cursor_row, grid.cursor_col)`.  Cursor colour is a fixed bright
    /// cyan tied to Synthia's accent (`#22d3ee`) so it stays visible even
    /// when the current SGR foreground is dim.  If a glyph occupies that
    /// cell we redraw it in dark over the cursor block so it stays legible.
    pub fn draw_cursor(&mut self, grid: &Grid) {
        let row = grid.cursor_row.min(grid.rows.saturating_sub(1));
        let col = grid.cursor_col.min(grid.cols.saturating_sub(1));
        let cell = grid.cell_at(row, col);
        let cursor_color = Color::rgb(0x22, 0xd3, 0xee);
        self.fill_cell_bg(row, col, cursor_color);
        if cell.ch != ' ' {
            let inverted = Cell {
                ch: cell.ch,
                fg: Color::rgb(0x0a, 0x0b, 0x14),
                bg: cursor_color,
                bold: cell.bold,
            };
            self.draw_glyph(row, col, inverted);
        }
    }

    /// Fill the entire surface with the panel background colour and present
    /// it.  Used by detach to make the subsurface visually disappear without
    /// destroying it — bypasses Wayland's parent-commit requirement on
    /// subsurface destroy.
    pub fn paint_blank(&mut self) {
        self.fill_background(Color::black());
    }

    pub fn fill_cell_bg(&mut self, row: usize, col: usize, color: Color) {
        let pixel = pack_color(color);
        let x0 = (col as u32) * self.cell_w + PADDING_X;
        let y0 = (row as u32) * self.cell_h + PADDING_Y;
        for dy in 0..self.cell_h {
            let y = y0 + dy;
            if y >= self.height {
                break;
            }
            for dx in 0..self.cell_w {
                let x = x0 + dx;
                if x >= self.width {
                    break;
                }
                self.buffer[(y * self.width + x) as usize] = pixel;
            }
        }
    }

    /// Rasterize one character via ab_glyph, anchored at cell origin.
    ///
    /// Tries the primary (Commit Mono) face first.  When `glyph_id == 0`
    /// (.notdef — character unsupported) we retry with the fallback face,
    /// which covers box-drawing, geometric shapes, braille, arrows, and
    /// other Unicode glyphs that Claude Code, vim, fzf, etc. emit.
    pub fn draw_glyph(&mut self, row: usize, col: usize, cell: Cell) {
        if cell.ch == ' ' {
            return;
        }
        let x0 = (col as i32) * self.cell_w as i32 + PADDING_X as i32;
        let y0 = (row as i32) * self.cell_h as i32 + PADDING_Y as i32;
        let baseline_y = y0 + self.fonts.ascent.ceil() as i32;

        let primary_gid = self.fonts.face.glyph_id(cell.ch);
        if primary_gid.0 != 0 {
            self.rasterize_with_primary(cell, x0, baseline_y, primary_gid);
            return;
        }
        // Primary lacks the glyph — walk the fallback chain.
        let fallbacks = self.fonts.fallbacks.clone();
        for fb in &fallbacks {
            let fb_gid = fb.glyph_id(cell.ch);
            if fb_gid.0 != 0 {
                self.rasterize_with_fallback(cell, x0, baseline_y, fb_gid, fb);
                return;
            }
        }
        // Nothing in the chain has the glyph — render Commit Mono's notdef
        // so at least *something* shows where the character would have gone.
        self.rasterize_with_primary(cell, x0, baseline_y, primary_gid);
    }

    fn rasterize_with_primary(
        &mut self,
        cell: Cell,
        x0: i32,
        baseline_y: i32,
        gid: ab_glyph::GlyphId,
    ) {
        let scaled = self.fonts.face.as_scaled(self.fonts.scale);
        let glyph = gid.with_scale_and_position(
            self.fonts.scale,
            ab_glyph::point(x0 as f32, baseline_y as f32),
        );
        if let Some(outlined) = scaled.font().outline_glyph(glyph) {
            self.blit_outlined(cell, outlined);
        }
    }

    fn rasterize_with_fallback(
        &mut self,
        cell: Cell,
        x0: i32,
        baseline_y: i32,
        gid: ab_glyph::GlyphId,
        fallback: &FontArc,
    ) {
        // Fallbacks (DejaVu Sans Mono, Noto Symbols2) often have wider
        // natural advance than Commit Mono.  Centre the glyph horizontally
        // in our fixed cell so it doesn't overflow into the next column.
        let fb_scaled = fallback.as_scaled(self.fonts.scale);
        let advance = fb_scaled.h_advance(gid);
        let cell_w = self.cell_w as f32;
        let x_offset = if advance > cell_w {
            // Tight glyph — squash by shifting half the overflow left.
            -((advance - cell_w) / 2.0)
        } else {
            (cell_w - advance) / 2.0
        };
        let glyph = gid.with_scale_and_position(
            self.fonts.scale,
            ab_glyph::point(x0 as f32 + x_offset, baseline_y as f32),
        );
        if let Some(outlined) = fb_scaled.font().outline_glyph(glyph) {
            self.blit_outlined(cell, outlined);
        }
    }

    fn blit_outlined(&mut self, cell: Cell, outlined: ab_glyph::OutlinedGlyph) {
        let bg = pack_color(cell.bg);
        let fg = pack_color(cell.fg);
        let width = self.width;
        let height = self.height;
        let buf = &mut self.buffer;
        let bb = outlined.px_bounds();
        outlined.draw(|gx, gy, alpha| {
            let px = bb.min.x as i32 + gx as i32;
            let py = bb.min.y as i32 + gy as i32;
            if px < 0 || py < 0 {
                return;
            }
            let (px, py) = (px as u32, py as u32);
            if px >= width || py >= height {
                return;
            }
            let alpha_byte = (alpha * 255.0) as u8;
            if alpha_byte == 0 {
                return;
            }
            buf[(py * width + px) as usize] = blend_alpha(bg, fg, alpha_byte);
        });
    }
}

// ---------------------------------------------------------------------------
// Pixel helpers
// ---------------------------------------------------------------------------

#[allow(dead_code)]
/// Inclusive cell-in-selection test treating the range as row-major.
fn cell_in_range(
    r: usize,
    c: usize,
    r0: usize,
    c0: usize,
    r1: usize,
    c1: usize,
    _cols: usize,
) -> bool {
    if r < r0 || r > r1 {
        return false;
    }
    if r0 == r1 {
        return c >= c0 && c <= c1;
    }
    if r == r0 {
        return c >= c0;
    }
    if r == r1 {
        return c <= c1;
    }
    true
}

pub fn pack_color(c: Color) -> u32 {
    // softbuffer expects 0x00RRGGBB.
    ((c.r as u32) << 16) | ((c.g as u32) << 8) | (c.b as u32)
}

pub fn blend_alpha(bg: u32, fg: u32, alpha: u8) -> u32 {
    let a = alpha as u32;
    let inv = 255 - a;
    let br = ((bg >> 16) & 0xff) * inv / 255;
    let bg_g = ((bg >> 8) & 0xff) * inv / 255;
    let bb = (bg & 0xff) * inv / 255;
    let fr = ((fg >> 16) & 0xff) * a / 255;
    let fg_g = ((fg >> 8) & 0xff) * a / 255;
    let fb = (fg & 0xff) * a / 255;
    ((br + fr) << 16) | ((bg_g + fg_g) << 8) | (bb + fb)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renderer_init_fails_on_zero_dim() {
        assert!(Renderer::new(0, 100, 8, 16, 13.0).is_err());
        assert!(Renderer::new(100, 0, 8, 16, 13.0).is_err());
    }

    #[test]
    fn renderer_fills_background() {
        let mut r = Renderer::new(4, 4, 2, 2, 13.0).unwrap();
        r.fill_background(Color::rgb(0xff, 0, 0));
        let expected = pack_color(Color::rgb(0xff, 0, 0));
        assert!(r.buffer.iter().all(|&p| p == expected));
    }

    #[test]
    fn renderer_paints_cell_bg() {
        // Buffer must be large enough to reach the padded cell origin.
        // cell (0,0) starts at (PADDING_X, PADDING_Y) = (14, 10).
        // Use a 64×64 surface with cell_w=8, cell_h=16.
        let w = 64u32;
        let h = 64u32;
        let cw = 8u32;
        let ch = 16u32;
        let mut r = Renderer::new(w, h, cw, ch, 13.0).unwrap();
        r.fill_background(Color::black());
        r.fill_cell_bg(0, 0, Color::rgb(0xff, 0, 0));
        let red = pack_color(Color::rgb(0xff, 0, 0));
        // First pixel of cell (0,0) is at (PADDING_X, PADDING_Y).
        let idx = (PADDING_Y * w + PADDING_X) as usize;
        assert_eq!(r.buffer[idx], red);
    }

    #[test]
    fn renderer_blend_alpha_zero_keeps_bg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 0), 0xffffff);
    }

    #[test]
    fn renderer_blend_alpha_full_uses_fg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 255), 0x000000);
    }

    #[test]
    fn measure_cell_returns_nonzero() {
        let (w, h) = measure_cell(13.5);
        assert!(w > 0);
        assert!(h > 0);
    }

    #[test]
    fn font_stack_advance_reasonable_for_commit_mono() {
        // Commit Mono at 13.5pt / 96 DPI → px_size ≈ 18px.
        // Monospace advance is typically 50–60 % of em, so ~9–11 px.
        let stack = FontStack::new(13.5);
        let adv = stack.advance();
        assert!((7..=20).contains(&adv), "advance {adv} out of expected range 7–20");
    }
}
