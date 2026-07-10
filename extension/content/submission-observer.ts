export function observeSubmissionConfirmation(onSubmitted: () => void): () => void {
  let reported = false
  const check = () => {
    if (reported) return
    const text = document.body.textContent?.toLowerCase() || ""
    const url = window.location.href.toLowerCase()
    const confirmed =
      url.includes("confirmation") ||
      text.includes("application submitted") ||
      text.includes("thank you for applying") ||
      text.includes("thanks for applying")
    if (confirmed) {
      reported = true
      onSubmitted()
    }
  }
  const observer = new MutationObserver(check)
  observer.observe(document.body, { childList: true, subtree: true })
  check()
  return () => observer.disconnect()
}
