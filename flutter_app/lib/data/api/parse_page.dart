/// 後端 cursor 分頁回應的共用解析：`{data: [...], pagination: {nextCursor, hasMore, totalCount}}`。
/// 各 API 的欄位名與 fallback（totalCount 缺時用本頁筆數）都在這一處。
typedef CursorPage<T> = ({List<T> data, String? nextCursor, bool hasMore, int totalCount});

CursorPage<T> parsePage<T>(dynamic body, T Function(Map) fromJson) {
  final data = body as Map;
  final list = (data['data'] as List? ?? const []).map((e) => fromJson(e as Map)).toList();
  final p = (data['pagination'] as Map?) ?? const {};
  return (
    data: list,
    nextCursor: p['nextCursor'] as String?,
    hasMore: (p['hasMore'] ?? false) as bool,
    totalCount: (p['totalCount'] as num?)?.toInt() ?? list.length,
  );
}
