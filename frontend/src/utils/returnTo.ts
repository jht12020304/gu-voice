// 登入後要回去的網址（iOS App「在網頁開啟」直接開 /:lng/reports/:sessionId，未登入時
// 先被帶去登入頁）。只接受站內報告路徑，避免 router state 被拿來導到任意位置。
export function safeReturnTo(from: unknown, lng: string): string {
  return typeof from === 'string' && /^\/[a-z]{2}-[A-Z]{2}\/reports(\/[\w-]+)?$/.test(from) ? from : `/${lng}/reports`;
}
