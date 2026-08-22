import 'package:flutter/material.dart';

import '../../core/theme/app_tokens.dart';

// 全 App 視覺統一元件包（2026-08-22，儀表板重排 PR #69 定調後鋪到所有頁面）。
//
// 設計規則（design-taste-frontend）：
//   - 容器圓角鎖 8（跟全域 CardTheme 一致）；標籤一律「12% 底色 + 同色字」的
//     pill（與既有 StatusBadge 同形）——兩形系統：容器=8、標籤=pill，不再出現
//     radius 4 的方形 badge。
//   - 載入狀態用「同形狀的骨架佔位」，不用置中轉圈（畫面不跳動）。
//   - 空狀態／錯誤狀態是有 icon、有標題、有訊息的組合，不是裸文字。
//   - 語意色（alert*/status*）只用來表達狀態，不當裝飾（不做彩色頂邊）。
//   - 單一 accent（theme primary）；icon 色塊統一 12% alpha 底。
//
// 頁面只從這裡拿元件，不要各自複製樣式——樣式分叉就是這次重排要解掉的病。

/// 36×36 圓角 8 的染色 icon 方塊（列表列 leading／區塊圖示）。
/// [color] 不給時用 theme primary；語意場景（警示列）才傳 alert 色。
class IconTile extends StatelessWidget {
  const IconTile(this.icon, {super.key, this.color, this.size = 36});

  final IconData icon;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.primary;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Icon(icon, size: size * 0.55, color: c),
    );
  }
}

/// 12% 底色 pill 標籤（severity／unread／狀態計數……）。
/// 與 StatusBadge 同形；新程式碼一律用這個，不再手刻 Container。
class PillTag extends StatelessWidget {
  const PillTag(this.text, {super.key, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(9999),
      ),
      child: Text(
        text,
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// 列表分組標頭（日期分組、章節）。統一 inkMuted + 些微 letterSpacing，
/// 對齊儀表板「管理區」的寫法。
class GroupHeader extends StatelessWidget {
  const GroupHeader(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 12, 4, 8),
      child: Text(
        text,
        style: Theme.of(context)
            .textTheme
            .labelMedium
            ?.copyWith(color: tk.inkMuted, letterSpacing: 0.5),
      ),
    );
  }
}

/// 空狀態：染色 icon 圓 + 標題 + 訊息（置中）。
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.message,
  });

  final IconData icon;
  final String title;
  final String? message;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: tk.inkMuted.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, size: 30, color: tk.inkMuted),
          ),
          const SizedBox(height: 16),
          Text(title,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w600),
              textAlign: TextAlign.center),
          if (message != null && message!.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(message!,
                style: Theme.of(context)
                    .textTheme
                    .bodyMedium
                    ?.copyWith(color: tk.inkSecondary),
                textAlign: TextAlign.center),
          ],
        ]),
      ),
    );
  }
}

/// 錯誤狀態：警示 icon 圓 + 訊息 + 重試鈕。retryLabel 由呼叫端帶
/// （沿用各頁既有的 t('common.retry')，本檔不 import i18n——kit 保持純視覺）。
class ErrorState extends StatelessWidget {
  const ErrorState({
    super.key,
    required this.message,
    required this.retryLabel,
    required this.onRetry,
  });

  final String message;
  final String retryLabel;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: tk.alertCritical.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.error_outline, size: 30, color: tk.alertCritical),
          ),
          const SizedBox(height: 16),
          Text(message,
              style: Theme.of(context).textTheme.bodyMedium,
              textAlign: TextAlign.center),
          const SizedBox(height: 16),
          FilledButton(onPressed: onRetry, child: Text(retryLabel)),
        ]),
      ),
    );
  }
}

/// 靜態骨架方塊（無動畫——動效極簡、天然符合 reduce-motion）。
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({super.key, required this.width, required this.height, this.radius = 6});

  final double width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: tk.edge,
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}

/// 列表載入骨架：N 張「圓 + 兩行」的佔位卡，形狀貼近真列表列。
class SkeletonList extends StatelessWidget {
  const SkeletonList({super.key, this.rows = 6});

  final int rows;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      physics: const NeverScrollableScrollPhysics(),
      children: [
        for (var i = 0; i < rows; i++)
          Card(
            margin: const EdgeInsets.symmetric(vertical: 4),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(children: [
                const SkeletonBox(width: 36, height: 36, radius: 18),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
                    SkeletonBox(width: 140, height: 14),
                    SizedBox(height: 8),
                    SkeletonBox(width: 220, height: 12),
                  ]),
                ),
              ]),
            ),
          ),
      ],
    );
  }
}

/// 統計格：標籤在上（inkSecondary）、大數字在下（tabular figures）。
/// [valueColor] 只在語意成立時傳（例：紅旗 > 0 → alertCritical），平常中性。
class StatCell extends StatelessWidget {
  const StatCell({
    super.key,
    required this.label,
    required this.value,
    this.loading = false,
    this.valueColor,
    this.compact = false,
  });

  final String label;
  final String value;
  final bool loading;
  final Color? valueColor;

  /// compact：值改用 titleLarge——給「值可能是長字串」的統計格
  /// （例：研究頁的「3.3 (2.6–4.2)」中位數＋IQR，headlineMedium 會在
  /// iPhone 半寬卡裡斷行斷在括號中間）。純數字的格維持預設大字。
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tk.inkSecondary)),
      const SizedBox(height: 6),
      if (loading)
        const SkeletonBox(width: 56, height: 32)
      else
        // FittedBox(scaleDown)：值在無界寬度下排成單行、放不下就整行縮字——
        // 統計值**永遠不換行**（「3.3 (2.6–4.2)」在半寬卡曾斷行斷在括號中間，
        // 光縮字級（compact）治標不治本，改成物理上不可能換行）。
        Align(
          alignment: Alignment.centerLeft,
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(value,
                maxLines: 1,
                style: (compact
                        ? Theme.of(context).textTheme.titleLarge
                        : Theme.of(context).textTheme.headlineMedium)
                    ?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: valueColor ?? tk.inkHeading,
                  fontFeatures: const [FontFeature.tabularFigures()],
                )),
          ),
        ),
    ]);
  }
}

/// 月份步進統計卡：標題列（月份靠左、‹ › 靠右）＋ hairline ＋ 統計格橫排。
/// 儀表板與病患列表共用；月份只在這張卡出現一次，別再在頁面其他地方重複它。
class MonthStatsCard extends StatelessWidget {
  const MonthStatsCard({
    super.key,
    required this.monthLabel,
    required this.prevTooltip,
    required this.nextTooltip,
    required this.onPrev,
    required this.onNext,
    required this.cells,
  });

  final String monthLabel;
  final String prevTooltip;
  final String nextTooltip;
  final VoidCallback? onPrev; // null = 載入中鎖定
  final VoidCallback? onNext;
  final List<StatCell> cells;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Card(
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
          child: Row(children: [
            Expanded(
              child: Text(monthLabel,
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600, color: tk.inkHeading)),
            ),
            IconButton(
              icon: const Icon(Icons.chevron_left),
              color: tk.inkSecondary,
              tooltip: prevTooltip,
              onPressed: onPrev,
            ),
            IconButton(
              icon: const Icon(Icons.chevron_right),
              color: tk.inkSecondary,
              tooltip: nextTooltip,
              onPressed: onNext,
            ),
          ]),
        ),
        Divider(height: 1, thickness: 1, color: tk.edge),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (var i = 0; i < cells.length; i++) ...[
              if (i > 0) ...[
                Container(width: 1, height: 48, color: tk.edge),
                const SizedBox(width: 16),
              ],
              Expanded(child: cells[i]),
            ],
          ]),
        ),
      ]),
    );
  }
}
