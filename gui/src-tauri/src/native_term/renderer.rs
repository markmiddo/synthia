//! Software rendering: softbuffer pixel buffer + cosmic-text glyph blit.

use crate::error::{AppError, AppResult};
use crate::native_term::grid::{Cell, Color, Grid};
use cosmic_text::{Attrs, Buffer, FontSystem, Metrics, Shaping, SwashCache};

#[allow(dead_code)]
pub struct FontStack {
    pub system: FontSystem,
    pub cache: SwashCache,
    pub metrics: Metrics,
}

impl FontStack {
    pub fn new(font_size: f32) -> Self {
        let system = FontSystem::new();
        let cache = SwashCache::new();
        let metrics = Metrics::new(font_size, font_size * 1.4);
        Self { system, cache, metrics }
    }
}

#[allow(dead_code)] // populated by attach (D Task 14)
pub struct Renderer {
    pub width: u32,
    pub height: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub buffer: Vec<u32>,
    pub fonts: FontStack,
}

#[allow(dead_code)] // wired up in attach (D Task 14)
impl Renderer {
    pub fn new(width: u32, height: u32, cell_w: u32, cell_h: u32, font_size: f32) -> AppResult<Self> {
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

    pub fn render_grid(&mut self, grid: &Grid) {
        self.fill_background(Color::black());
        for r in 0..grid.rows {
            for c in 0..grid.cols {
                let cell = grid.cell_at(r, c);
                if cell.bg != Color::black() {
                    self.fill_cell_bg(r, c, cell.bg);
                }
                if cell.ch != ' ' {
                    self.draw_glyph(r, c, cell);
                }
            }
        }
    }

    pub fn fill_cell_bg(&mut self, row: usize, col: usize, color: Color) {
        let pixel = pack_color(color);
        let x0 = (col as u32) * self.cell_w;
        let y0 = (row as u32) * self.cell_h;
        for dy in 0..self.cell_h {
            let y = y0 + dy;
            if y >= self.height { break; }
            for dx in 0..self.cell_w {
                let x = x0 + dx;
                if x >= self.width { break; }
                self.buffer[(y * self.width + x) as usize] = pixel;
            }
        }
    }

    pub fn draw_glyph(&mut self, row: usize, col: usize, cell: Cell) {
        let x0 = (col as i32) * self.cell_w as i32;
        let y0 = (row as i32) * self.cell_h as i32;

        let mut ct_buf = Buffer::new(&mut self.fonts.system, self.fonts.metrics);
        let attrs = Attrs::new();
        let s = cell.ch.to_string();
        ct_buf.set_size(
            &mut self.fonts.system,
            Some(self.cell_w as f32),
            Some(self.cell_h as f32),
        );
        ct_buf.set_text(&mut self.fonts.system, &s, attrs, Shaping::Advanced);
        ct_buf.shape_until_scroll(&mut self.fonts.system, false);

        let bg = pack_color(cell.bg);
        let fg = pack_color(cell.fg);
        let width = self.width;
        let height = self.height;
        let buffer_pixels = &mut self.buffer;
        let fonts = &mut self.fonts;

        for run in ct_buf.layout_runs() {
            for glyph in run.glyphs.iter() {
                let physical = glyph.physical((0.0, 0.0), 1.0);
                let line_y = run.line_y as i32;
                fonts.cache.with_pixels(
                    &mut fonts.system,
                    physical.cache_key,
                    cosmic_text::Color::rgb(cell.fg.r, cell.fg.g, cell.fg.b),
                    |gx, gy, color| {
                        let alpha = color.a();
                        if alpha == 0 { return; }
                        // Do not add physical.x here — that is the glyph's
                        // advance/layout position relative to the buffer origin,
                        // which would push it past the cell's left edge and cause
                        // inter-character gaps ("m a r k" instead of "mark").
                        // The glyph pixels in the callback are already relative to
                        // the glyph's own top-left, so we only need the cell origin.
                        let px = x0 + gx;
                        let py = y0 + line_y + gy;
                        if px < 0 || py < 0 { return; }
                        let (px, py) = (px as u32, py as u32);
                        if px >= width || py >= height { return; }
                        let blended = blend_alpha(bg, fg, alpha);
                        buffer_pixels[(py * width + px) as usize] = blended;
                    },
                );
            }
        }
    }
}

#[allow(dead_code)]
pub fn pack_color(c: Color) -> u32 {
    // softbuffer expects 0xRRGGBB packed, alpha ignored.
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

/// Measure cell dimensions for a monospace font at the given size.
/// Returns `(advance_width_px, line_height_px)`, both ceil'd to whole pixels.
/// Uses cosmic-text to shape the letter 'M' and read its glyph advance width.
pub fn measure_cell(system: &mut FontSystem, font_size: f32) -> (u32, u32) {
    let metrics = Metrics::new(font_size, font_size * 1.4);
    let mut buffer = Buffer::new(system, metrics);
    buffer.set_size(system, Some(1024.0), Some(metrics.line_height));
    buffer.set_text(system, "M", Attrs::new(), Shaping::Advanced);
    buffer.shape_until_scroll(system, false);
    // Fallback: ~0.6em for a typical monospace face.
    let mut advance: f32 = font_size * 0.6;
    for run in buffer.layout_runs() {
        for g in run.glyphs.iter() {
            if g.w > advance {
                advance = g.w;
            }
        }
    }
    let cell_w = advance.ceil() as u32;
    let cell_h = metrics.line_height.ceil() as u32;
    (cell_w.max(1), cell_h.max(1))
}

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
        let mut r = Renderer::new(4, 4, 2, 2, 13.0).unwrap();
        r.fill_background(Color::black());
        r.fill_cell_bg(0, 0, Color::rgb(0xff, 0, 0));
        let red = pack_color(Color::rgb(0xff, 0, 0));
        assert_eq!(r.buffer[0], red);
    }

    #[test]
    fn renderer_blend_alpha_zero_keeps_bg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 0), 0xffffff);
    }

    #[test]
    fn renderer_blend_alpha_full_uses_fg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 255), 0x000000);
    }
}
