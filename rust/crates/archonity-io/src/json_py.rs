//! Запись JSON как `json.dump(..., ensure_ascii=False, indent=1)` в Python: пробелы, `repr` чисел, порядок ключей.

use serde_json::Value as Json;

pub fn dumps_indent1(_v: &Json) -> String {
    todo!("P2")
}
