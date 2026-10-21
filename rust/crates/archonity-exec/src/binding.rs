//! R20 (`engine/grounding/binding.py`): обработчик, который Spring вызвать не может, — шаг через рабочий обработчик
//! того же контроллера. Вход — шаг до замены.

use archonity_model::StepRequest;

use crate::catalog::HandlerCatalog;

pub fn rebind(_catalog: &HandlerCatalog, _req: &StepRequest) -> Option<StepRequest> {
    todo!("P3")
}
