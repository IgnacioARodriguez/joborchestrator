const DEFAULT_ERROR = "No se pudo completar la acción. Intenta nuevamente."

export function userFacingError(error: unknown, fallback = DEFAULT_ERROR) {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : ""
  const message = raw.trim()
  const normalized = message.toLowerCase()
  if (!message || normalized === "backend request failed.") return fallback
  if (/failed to fetch|networkerror|network request|load failed|offline/.test(normalized)) return "No se pudo conectar con JobOrchestrator. Comprueba la conexión e intenta nuevamente."
  if (/401|unauthorized|not authenticated/.test(normalized)) return "Tu sesión ya no es válida. Vuelve a iniciar sesión e intenta nuevamente."
  if (/403|forbidden|permission/.test(normalized)) return "No tienes permiso para realizar esta acción."
  if (/404|not found/.test(normalized)) return "La información ya no está disponible. Actualiza la pantalla e intenta nuevamente."
  if (/409|already running|already exists|conflict/.test(normalized)) return "Esta acción ya está en curso o acaba de completarse. Actualiza la pantalla para ver el estado."
  if (/422|validation|invalid/.test(normalized)) return "Hay información incompleta o inválida. Revisa los datos e intenta nuevamente."
  if (/429|rate limit|too many requests|500|502|503|504|internal server|service unavailable|gateway/.test(normalized)) return "El servicio tuvo un problema temporal. Intenta nuevamente."
  if (/worker|localhost|127\.0\.0\.1/.test(normalized)) return "El asistente local no está disponible. Inícialo y vuelve a intentar la acción."
  if (/traceback|exception|stack trace|sqlite|sql |json decode|http status/.test(normalized)) return fallback
  return message.length <= 180 ? message : fallback
}
