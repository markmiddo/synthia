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
            b'm' => {
                // SGR: select graphic rendition
                if params.is_empty() || params == [0] {
                    self.fg = Color::white();
                    self.bg = Color::black();
                    self.bold = false;
                } else {
                    for &p in params {
                        match p {
                            0 => { self.fg = Color::white(); self.bg = Color::black(); self.bold = false; }
                            1 => self.bold = true,
                            22 => self.bold = false,
                            30 => self.fg = Color::black(),
                            31 => self.fg = Color::rgb(0xfd, 0xa4, 0xaf),
                            32 => self.fg = Color::rgb(0x86, 0xef, 0xac),
                            33 => self.fg = Color::rgb(0xfd, 0xe6, 0x8a),
                            34 => self.fg = Color::rgb(0xa5, 0xb4, 0xfc),
                            35 => self.fg = Color::rgb(0xc4, 0xb5, 0xfd),
                            36 => self.fg = Color::rgb(0x67, 0xe8, 0xf9),
                            37 => self.fg = Color::white(),
                            39 => self.fg = Color::white(),
                            40 => self.bg = Color::black(),
                            41 => self.bg = Color::rgb(0xfd, 0xa4, 0xaf),
                            42 => self.bg = Color::rgb(0x86, 0xef, 0xac),
                            43 => self.bg = Color::rgb(0xfd, 0xe6, 0x8a),
                            44 => self.bg = Color::rgb(0xa5, 0xb4, 0xfc),
                            45 => self.bg = Color::rgb(0xc4, 0xb5, 0xfd),
                            46 => self.bg = Color::rgb(0x67, 0xe8, 0xf9),
                            47 => self.bg = Color::white(),
                            49 => self.bg = Color::black(),
                            90..=97 => {
                                self.fg = match p {
                                    90 => Color::rgb(0x6b, 0x72, 0x80),
                                    91 => Color::rgb(0xfb, 0x71, 0x85),
                                    92 => Color::rgb(0x4a, 0xde, 0x80),
                                    93 => Color::rgb(0xfa, 0xcc, 0x15),
                                    94 => Color::rgb(0x81, 0x8c, 0xf8),
                                    95 => Color::rgb(0xa7, 0x8b, 0xfa),
                                    96 => Color::rgb(0x22, 0xd3, 0xee),
                                    _  => Color::rgb(0xff, 0xff, 0xff),
                                };
                            }
                            _ => { /* unhandled SGR — silent */ }
                        }
                    }
                }
            }
            b'J' => {
                // ED: erase display. param 2 = entire screen.
                let n = params.first().copied().unwrap_or(0);
                if n == 2 {
                    let blank = Cell { ch: ' ', fg: self.fg, bg: self.bg, bold: false };
                    self.cells.iter_mut().for_each(|c| *c = blank);
                }
            }
            b'K' => {
                // EL: erase in line. 0=cursor→EOL (default), 1=BOL→cursor, 2=entire line.
                let n = params.first().copied().unwrap_or(0);
                let blank = Cell { ch: ' ', fg: self.fg, bg: self.bg, bold: false };
                let row = self.cursor_row;
                let row_start = row * self.cols;
                let (lo, hi) = match n {
                    1 => (0usize, self.cursor_col + 1),
                    2 => (0usize, self.cols),
                    _ => (self.cursor_col, self.cols),
                };
                for c in lo..hi.min(self.cols) {
                    self.cells[row_start + c] = blank;
                }
            }
            _ => { /* unhandled — silent */ }
        }
        self.dirty = true;
    }

    pub fn resize(&mut self, rows: usize, cols: usize) {
        let mut new_cells = vec![Cell::default(); rows * cols];
        let copy_rows = self.rows.min(rows);
        let copy_cols = self.cols.min(cols);
        for r in 0..copy_rows {
            for c in 0..copy_cols {
                new_cells[r * cols + c] = self.cells[r * self.cols + c];
            }
        }
        self.rows = rows;
        self.cols = cols;
        self.cells = new_cells;
        self.cursor_row = self.cursor_row.min(rows.saturating_sub(1));
        self.cursor_col = self.cursor_col.min(cols.saturating_sub(1));
        self.dirty = true;
    }
}

impl vte::Perform for Grid {
    fn print(&mut self, ch: char) {
        self.apply_print(ch);
    }
    fn execute(&mut self, byte: u8) {
        match byte {
            b'\n' => {
                self.cursor_row = (self.cursor_row + 1).min(self.rows.saturating_sub(1));
                self.dirty = true;
            }
            b'\r' => { self.cursor_col = 0; self.dirty = true; }
            0x08 => {
                self.cursor_col = self.cursor_col.saturating_sub(1);
                let idx = self.cursor_row * self.cols + self.cursor_col;
                if idx < self.cells.len() {
                    self.cells[idx] = Cell { ch: ' ', fg: self.fg, bg: self.bg, bold: false };
                }
                self.dirty = true;
            }
            0x07 => { /* bell — ignore */ }
            _ => {}
        }
    }
    fn csi_dispatch(&mut self, params: &vte::Params, _intermediates: &[u8], _ignore: bool, action: char) {
        let nums: Vec<u16> = params.iter().map(|p| p.first().copied().unwrap_or(0)).collect();
        Grid::csi_dispatch(self, action as u8, &nums);
    }
    fn esc_dispatch(&mut self, _intermediates: &[u8], _ignore: bool, _byte: u8) {}
    fn osc_dispatch(&mut self, _params: &[&[u8]], _bell_terminated: bool) {}
    fn hook(&mut self, _params: &vte::Params, _intermediates: &[u8], _ignore: bool, _action: char) {}
    fn put(&mut self, _byte: u8) {}
    fn unhook(&mut self) {}
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

    #[test]
    fn grid_csi_sgr_red_fg() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[31]);
        g.apply_print('R');
        assert_eq!(g.cell_at(0, 0).fg, Color::rgb(0xfd, 0xa4, 0xaf));
    }

    #[test]
    fn grid_csi_sgr_reset() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[31]);
        g.csi_dispatch(b'm', &[0]);
        g.apply_print('X');
        assert_eq!(g.cell_at(0, 0).fg, Color::white());
        assert!(!g.cell_at(0, 0).bold);
    }

    #[test]
    fn grid_csi_sgr_bold() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[1]);
        g.apply_print('B');
        assert!(g.cell_at(0, 0).bold);
    }

    #[test]
    fn grid_csi_ed_clears_screen() {
        let mut g = Grid::new(2, 3);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.csi_dispatch(b'J', &[2]);
        for r in 0..g.rows {
            for c in 0..g.cols {
                assert_eq!(g.cell_at(r, c).ch, ' ');
            }
        }
    }

    #[test]
    fn grid_csi_el_clears_line() {
        let mut g = Grid::new(2, 3);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.cursor_row = 0; g.cursor_col = 0;
        g.csi_dispatch(b'K', &[2]);
        for c in 0..g.cols {
            assert_eq!(g.cell_at(0, c).ch, ' ');
        }
    }

    #[test]
    fn vte_performer_handles_print() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        for &b in b"hi" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'h');
        assert_eq!(g.cell_at(0, 1).ch, 'i');
    }

    #[test]
    fn vte_performer_handles_color_seq() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        // \x1b[31m R \x1b[0m
        for &b in b"\x1b[31mR\x1b[0m" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'R');
        assert_eq!(g.cell_at(0, 0).fg, Color::rgb(0xfd, 0xa4, 0xaf));
    }

    #[test]
    fn vte_performer_newline() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        for &b in b"a\nb" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(1, 1).ch, 'b'); // \n moves down + col stays at 1
    }

    #[test]
    fn grid_resize_preserves_visible_cells() {
        let mut g = Grid::new(3, 5);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.resize(5, 10);
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(0, 1).ch, 'b');
        assert_eq!(g.cell_at(0, 2).ch, 'c');
        assert_eq!(g.rows, 5);
        assert_eq!(g.cols, 10);
    }

    #[test]
    fn grid_resize_smaller_drops_overflow() {
        let mut g = Grid::new(5, 10);
        for ch in "abcdefghij".chars() { g.apply_print(ch); }
        g.resize(2, 5);
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.rows, 2);
        assert_eq!(g.cols, 5);
        assert!(g.cursor_row < g.rows);
        assert!(g.cursor_col < g.cols);
    }
}
