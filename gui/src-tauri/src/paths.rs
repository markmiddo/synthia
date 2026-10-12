//! Filename and path-traversal safety helpers.

use crate::error::{AppError, AppResult};

/// Validate a single filename has no path separators, parent refs, or hidden-dot prefix.
///
/// Use this for inputs that are intended to be a single filename or directory
/// component. For multi-segment relative paths (e.g. `subdir/file.md`), use
/// [`validate_relative_path`] / [`safe_join_relative`] instead.
pub fn validate_filename(name: &str) -> AppResult<()> {
    if name.is_empty()
        || name.contains('/')
        || name.contains('\\')
        || name.contains("..")
        || name.starts_with('.')
    {
        return Err(AppError::Validation(format!("bad filename: {name}")));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_filename() {
        assert!(validate_filename("").is_err());
    }

    #[test]
    fn rejects_slash() {
        assert!(validate_filename("foo/bar").is_err());
    }

    #[test]
    fn rejects_backslash() {
        assert!(validate_filename("foo\\bar").is_err());
    }

    #[test]
    fn rejects_parent_ref() {
        assert!(validate_filename("..").is_err());
        assert!(validate_filename("foo..bar").is_err());
    }

    #[test]
    fn rejects_hidden_dotfile() {
        assert!(validate_filename(".env").is_err());
    }

    #[test]
    fn accepts_normal_filename() {
        assert!(validate_filename("notes.md").is_ok());
        assert!(validate_filename("my-file_2.txt").is_ok());
    }
}
