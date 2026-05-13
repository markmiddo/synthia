//! Software rendering: softbuffer pixel buffer + cosmic-text glyph blit.
//!
//! D Task 10: pixel buffer + cell background fill (this task).
//! D Task 11: cosmic-text glyph rendering on top.

use crate::error::{AppError, AppResult};
use crate::native_term::grid::{Color, Grid};

#[allow(dead_code)] // populated by attach (D Task 14)
pub struct Renderer {
    pub width: u32,
    pub height: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub buffer: Vec<u32>,
}

#[allow(dead_code)] // wired up in attach (D Task 14)
impl Renderer {
    pub fn new(width: u32, height: u32, cell_w: u32, cell_h: u32) -> AppResult<Self> {
        if width == 0 || height == 0 {
            return Err(AppError::Terminal("renderer: zero-dim surface".into()));
        }
        Ok(Self {
            width, height, cell_w, cell_h,
            buffer: vec![0u32; (width * height) as usize],
        })
    }

    pub fn fill_background(&mut self, bg: Color) {
        let pixel = pack_color(bg);
        self.buffer.iter_mut().for_each(|p| *p = pixel);
    }

    pub fn render_grid(&mut self, grid: &Grid) {
        // v1: fill entire surface with default bg, then paint cell-specific bgs.
        // Glyphs added in D Task 11.
        self.fill_background(Color::black());
        for r in 0..grid.rows {
            for c in 0..grid.cols {
                let cell = grid.cell_at(r, c);
                if cell.bg != Color::black() {
                    self.fill_cell_bg(r, c, cell.bg);
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
}

#[allow(dead_code)]
pub fn pack_color(c: Color) -> u32 {
    // softbuffer expects 0xRRGGBB packed, alpha ignored.
    ((c.r as u32) << 16) | ((c.g as u32) << 8) | (c.b as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renderer_init_fails_on_zero_dim() {
        assert!(Renderer::new(0, 100, 8, 16).is_err());
        assert!(Renderer::new(100, 0, 8, 16).is_err());
    }

    #[test]
    fn renderer_fills_background() {
        let mut r = Renderer::new(4, 4, 2, 2).unwrap();
        r.fill_background(Color::rgb(0xff, 0, 0));
        let expected = pack_color(Color::rgb(0xff, 0, 0));
        assert!(r.buffer.iter().all(|&p| p == expected));
    }

    #[test]
    fn renderer_paints_cell_bg() {
        let mut r = Renderer::new(4, 4, 2, 2).unwrap();
        r.fill_background(Color::black());
        r.fill_cell_bg(0, 0, Color::rgb(0xff, 0, 0));
        let red = pack_color(Color::rgb(0xff, 0, 0));
        assert_eq!(r.buffer[0], red);
        assert_eq!(r.buffer[1], red);
        assert_eq!(r.buffer[4], red);
        assert_eq!(r.buffer[5], red);
        // outside cell still black
        assert_eq!(r.buffer[2], pack_color(Color::black()));
    }
}
