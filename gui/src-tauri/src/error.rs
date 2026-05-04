//! Typed application errors with wire-format-preserving serialization.
//!
//! `AppError` serializes as a plain JSON string (the `Display` output) so that
//! existing React `invoke()` consumers — which receive errors as strings — keep
//! working unchanged. Internally we get typed errors and `?` propagation.

#[derive(Debug, thiserror::Error)]
#[allow(dead_code)] // some variants only appear in later checkpoints
pub enum AppError {
    #[error("io: {0}")]
    Io(String),
    #[error("yaml: {0}")]
    Yaml(String),
    #[error("json: {0}")]
    Json(String),
    #[error("path: {0}")]
    Path(String),
    #[error("validation: {0}")]
    Validation(String),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("process: {0}")]
    Process(String),
    #[error("http: {0}")]
    Http(String),
    #[error("other: {0}")]
    Other(String),
}

impl serde::Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Io(e.to_string())
    }
}

impl From<serde_yaml::Error> for AppError {
    fn from(e: serde_yaml::Error) -> Self {
        AppError::Yaml(e.to_string())
    }
}

impl From<serde_json::Error> for AppError {
    fn from(e: serde_json::Error) -> Self {
        AppError::Json(e.to_string())
    }
}

impl From<reqwest::Error> for AppError {
    fn from(e: reqwest::Error) -> Self {
        AppError::Http(e.to_string())
    }
}

impl From<String> for AppError {
    fn from(s: String) -> Self {
        AppError::Other(s)
    }
}

impl From<&str> for AppError {
    fn from(s: &str) -> Self {
        AppError::Other(s.to_string())
    }
}

pub type AppResult<T> = Result<T, AppError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serializes_as_plain_string() {
        let err = AppError::Validation("bad name".to_string());
        let json = serde_json::to_string(&err).unwrap();
        assert_eq!(json, "\"validation: bad name\"");
    }

    #[test]
    fn io_conversion_preserves_message() {
        let io = std::io::Error::new(std::io::ErrorKind::NotFound, "missing");
        let app: AppError = io.into();
        assert!(matches!(app, AppError::Io(_)));
        assert_eq!(app.to_string(), "io: missing");
    }
}
