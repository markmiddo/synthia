//! Terminal grid state. Implements `vte::Performer` to consume PTY bytes.
//!
//! v1 Cell = ASCII char + 16-color fg/bg + bold. No underline / italic / 256-color
//! palette / true-color in v1 — added incrementally.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Color {
    pub r: u8,
    pub g: u8,
    pub b: u8,
}

impl Color {
    pub const fn rgb(r: u8, g: u8, b: u8) -> Self { Self { r, g, b } }
    pub const fn black() -> Self { Self::rgb(0x1a, 0x1b, 0x26) }
    pub const fn white() -> Self { Self::rgb(0xe6, 0xe6, 0xfa) }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Cell {
    pub ch: char,
    pub fg: Color,
    pub bg: Color,
    pub bold: bool,
}

impl Default for Cell {
    fn default() -> Self {
        Self { ch: ' ', fg: Color::white(), bg: Color::black(), bold: false }
    }
}

#[allow(dead_code)] // wired up in renderer (D Task 10) and vte performer (D Task 7)
#[derive(Debug)]
pub struct Grid {
    pub rows: usize,
    pub cols: usize,
    pub cells: Vec<Cell>,
    pub cursor_row: usize,
    pub cursor_col: usize,
    pub fg: Color,
    pub bg: Color,
    pub bold: bool,
    pub dirty: bool,
}

#[allow(dead_code)] // wired up in renderer (D Task 10) and vte performer (D Task 7)
impl Grid {
    pub fn new(rows: usize, cols: usize) -> Self {
        Self {
            rows, cols,
            cells: vec![Cell::default(); rows * cols],
            cursor_row: 0, cursor_col: 0,
            fg: Color::white(), bg: Color::black(), bold: false,
            dirty: true,
        }
    }

    pub fn cell_at(&self, row: usize, col: usize) -> Cell {
        self.cells[row * self.cols + col]
    }

    pub fn apply_print(&mut self, ch: char) {
        if self.cursor_col >= self.cols {
            self.cursor_col = 0;
            self.cursor_row += 1;
        }
        if self.cursor_row >= self.rows {
            // scroll up by one line
            for r in 1..self.rows {
                for c in 0..self.cols {
                    self.cells[(r - 1) * self.cols + c] = self.cells[r * self.cols + c];
                }
            }
            for c in 0..self.cols {
                self.cells[(self.rows - 1) * self.cols + c] = Cell {
                    ch: ' ', fg: self.fg, bg: self.bg, bold: false,
                };
            }
            self.cursor_row = self.rows - 1;
        }
        let idx = self.cursor_row * self.cols + self.cursor_col;
        self.cells[idx] = Cell { ch, fg: self.fg, bg: self.bg, bold: self.bold };
        self.cursor_col += 1;
        self.dirty = true;
    }

    /// Dispatch a CSI sequence. `params` are decoded numeric parameters (0 if absent).
    pub fn csi_dispatch(&mut self, action: u8, params: &[u16]) {
        let p = |i: usize, default: u16| -> u16 {
            params.get(i).copied().filter(|&v| v != 0).unwrap_or(default)
        };
        match action {
            b'H' | b'f' => {
                // CUP: cursor position (1-based)
                let row = (p(0, 1) as usize).saturating_sub(1).min(self.rows.saturating_sub(1));
                let col = (p(1, 1) as usize).saturating_sub(1).min(self.cols.saturating_sub(1));
                self.cursor_row = row;
                self.cursor_col = col;
            }
            b'A' => {
                // CUU
                let n = p(0, 1) as usize;
                self.cursor_row = self.cursor_row.saturating_sub(n);
            }
            b'B' => {
                // CUD
                let n = p(0, 1) as usize;
                self.cursor_row = (self.cursor_row + n).min(self.rows.saturating_sub(1));
            }
            b'C' => {
                // CUF
                let n = p(0, 1) as usize;
                self.cursor_col = (self.cursor_col + n).min(self.cols.saturating_sub(1));
            }
            b'D' => {
                // CUB
                let n = p(0, 1) as usize;
                self.cursor_col = self.cursor_col.saturating_sub(n);
            }
            _ => { /* unhandled — silent for v1 */ }
        }
        self.dirty = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grid_apply_print_writes_at_cursor() {
        let mut g = Grid::new(5, 10);
        g.apply_print('A');
        assert_eq!(g.cell_at(0, 0).ch, 'A');
        assert_eq!(g.cursor_col, 1);
    }

    #[test]
    fn grid_apply_print_wraps_to_next_row() {
        let mut g = Grid::new(3, 3);
        for ch in "abcdef".chars() { g.apply_print(ch); }
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(0, 2).ch, 'c');
        assert_eq!(g.cell_at(1, 0).ch, 'd');
        assert_eq!(g.cell_at(1, 2).ch, 'f');
    }

    #[test]
    fn grid_apply_print_scrolls_when_full() {
        let mut g = Grid::new(2, 3);
        for ch in "abcdefghij".chars() { g.apply_print(ch); }
        // after 2 scrolls, grid has rows [g,h,i] and [j, ,  ]
        assert_eq!(g.cell_at(0, 0).ch, 'g');
        assert_eq!(g.cell_at(1, 0).ch, 'j');
    }

    #[test]
    fn grid_marks_dirty_on_print() {
        let mut g = Grid::new(2, 2);
        g.dirty = false;
        g.apply_print('x');
        assert!(g.dirty);
    }

    #[test]
    fn grid_csi_cup_moves_cursor() {
        let mut g = Grid::new(10, 20);
        // CSI 5;10H = cursor to row 5 col 10 (1-based)
        g.csi_dispatch(b'H', &[5, 10]);
        assert_eq!(g.cursor_row, 4);
        assert_eq!(g.cursor_col, 9);
    }

    #[test]
    fn grid_csi_cuf_advances_cursor() {
        let mut g = Grid::new(5, 10);
        g.cursor_col = 2;
        g.csi_dispatch(b'C', &[3]);
        assert_eq!(g.cursor_col, 5);
    }

    #[test]
    fn grid_csi_cub_retreats_cursor() {
        let mut g = Grid::new(5, 10);
        g.cursor_col = 5;
        g.csi_dispatch(b'D', &[2]);
        assert_eq!(g.cursor_col, 3);
    }

    #[test]
    fn grid_csi_cuu_moves_up() {
        let mut g = Grid::new(5, 10);
        g.cursor_row = 3;
        g.csi_dispatch(b'A', &[2]);
        assert_eq!(g.cursor_row, 1);
    }

    #[test]
    fn grid_csi_cud_moves_down() {
        let mut g = Grid::new(5, 10);
        g.cursor_row = 1;
        g.csi_dispatch(b'B', &[2]);
        assert_eq!(g.cursor_row, 3);
    }

    #[test]
    fn grid_csi_cup_clamps_to_bounds() {
        let mut g = Grid::new(5, 5);
        g.csi_dispatch(b'H', &[100, 100]);
        assert_eq!(g.cursor_row, 4);
        assert_eq!(g.cursor_col, 4);
    }
}
