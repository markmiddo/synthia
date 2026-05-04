//! Filename and path-traversal safety helpers.

use crate::error::{AppError, AppResult};
use std::path::{Path, PathBuf};

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

/// Validate a multi-segment *relative* path: no absolute roots, no `..`
/// segments, no empty/`.` segments, no NUL bytes.
///
/// Permits forward slashes between segments. Each segment is otherwise
/// subject to similar checks as [`validate_filename`] (no leading dot,
/// no backslash, non-empty).
pub fn validate_relative_path(rel: &str) -> AppResult<()> {
    if rel.is_empty() {
        return Err(AppError::Validation("empty path".into()));
    }
    if rel.contains('\0') {
        return Err(AppError::Validation("path contains NUL byte".into()));
    }
    let p = Path::new(rel);
    if p.is_absolute() {
        return Err(AppError::Validation(format!("absolute path not allowed: {rel}")));
    }
    for component in p.components() {
        use std::path::Component;
        match component {
            Component::Normal(seg) => {
                let s = seg.to_str().ok_or_else(|| {
                    AppError::Validation(format!("non-utf8 segment in: {rel}"))
                })?;
                if s.is_empty() || s.starts_with('.') || s.contains('\\') {
                    return Err(AppError::Validation(format!("bad segment in: {rel}")));
                }
            }
            Component::CurDir => {
                return Err(AppError::Validation(format!("`.` segment not allowed: {rel}")))
            }
            Component::ParentDir => {
                return Err(AppError::Validation(format!("`..` segment not allowed: {rel}")))
            }
            Component::RootDir | Component::Prefix(_) => {
                return Err(AppError::Validation(format!("absolute path not allowed: {rel}")))
            }
        }
    }
    Ok(())
}

/// Join a single-component `user_input` onto `base` and verify the canonical
/// result stays under base.
///
/// Both paths must exist on disk for canonicalization to succeed. For new-file
/// writes, validate the filename with `validate_filename` and canonicalize the
/// parent directory separately.
pub fn safe_join(base: &Path, user_input: &str) -> AppResult<PathBuf> {
    validate_filename(user_input)?;
    canonical_join(base, user_input)
}

/// Join a multi-segment relative `user_input` onto `base` and verify the
/// canonical result stays under base.
///
/// Both the joined path and the base must exist on disk. Use this for handlers
/// that accept relative paths with subdirectories (e.g. `subfolder/note.md`).
pub fn safe_join_relative(base: &Path, user_input: &str) -> AppResult<PathBuf> {
    validate_relative_path(user_input)?;
    canonical_join(base, user_input)
}

fn canonical_join(base: &Path, user_input: &str) -> AppResult<PathBuf> {
    let candidate = base.join(user_input);
    let canonical = candidate
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize {}: {}", candidate.display(), e)))?;
    let base_canonical = base
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize base {}: {}", base.display(), e)))?;
    if !canonical.starts_with(&base_canonical) {
        return Err(AppError::Validation(format!(
            "path escapes base: {user_input}"
        )));
    }
    Ok(canonical)
}

/// Resolve `parent_rel` (a relative path under `base`) and validate the
/// joined `filename` lands under `base`. Used for new-file writes where the
/// target file may not exist yet but its parent directory does.
///
/// Returns the absolute target path (parent canonicalized + filename joined).
/// Caller is responsible for `fs::write` / `fs::create_dir_all`.
pub fn safe_new_file(base: &Path, parent_rel: &str, filename: &str) -> AppResult<PathBuf> {
    validate_filename(filename)?;
    let parent = if parent_rel.is_empty() {
        base.to_path_buf()
    } else {
        validate_relative_path(parent_rel)?;
        base.join(parent_rel)
    };
    let parent_canonical = parent
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize parent {}: {}", parent.display(), e)))?;
    let base_canonical = base
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize base {}: {}", base.display(), e)))?;
    if !parent_canonical.starts_with(&base_canonical) {
        return Err(AppError::Validation(format!(
            "parent escapes base: {parent_rel}"
        )));
    }
    Ok(parent_canonical.join(filename))
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

    #[test]
    fn safe_join_blocks_traversal() {
        let tmp = std::env::temp_dir();
        assert!(safe_join(&tmp, "../etc/passwd").is_err());
    }

    #[test]
    fn validate_relative_path_rejects_traversal() {
        assert!(validate_relative_path("../etc/passwd").is_err());
        assert!(validate_relative_path("foo/../bar").is_err());
        assert!(validate_relative_path("/etc/passwd").is_err());
        assert!(validate_relative_path("").is_err());
        assert!(validate_relative_path("foo/.hidden").is_err());
        assert!(validate_relative_path("./foo").is_err());
    }

    #[test]
    fn validate_relative_path_accepts_nested() {
        assert!(validate_relative_path("foo").is_ok());
        assert!(validate_relative_path("foo/bar.md").is_ok());
        assert!(validate_relative_path("a/b/c/d.txt").is_ok());
    }
}
