import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/dashboard_api.dart';
import '../../auth/auth_notifier.dart';
import '../research/charts.dart';

// 醫師儀表板（2026-08-22 依 design-taste-frontend 重排）。
// 版面決策（對照重排前的截圖問題）：
//   - 月份原本出現三次（副標、置中步進器、統計卡標題）→ 收斂成一次：
//     月份步進器作為統計卡的標題列，統計標題用自帶月份語境的既有 key。
//   - 導航原本是三種寬度的 Outlined 藥丸鈕＋Wrap 散排 → 全部改成分組列表列
//     （icon 色塊＋標籤＋chevron），行動裝置上可掃讀、寬度一致。
//   - 圓角原本三種（藥丸 999／卡 8／CTA 4）→ 本頁鎖 8（跟全域 CardTheme 一致，
//     圖表卡也是 8）。
//   - 統計卡原本拿警示色當裝飾頂邊（紅邊≠有事）→ 語意色只在「紅旗 > 0」時
//     上到數字本身，0 時維持中性。
//   - 載入原本用轉圈取代整塊 → 改成同形狀的骨架佔位（數字位置放灰塊）。
// i18n：只重用既有 key（totalSessions／redFlagMetric／monthFormat／sidebar.nav.*），
// 不新增翻譯，五語 parity 檢查不受影響。
class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  MonthlySummary? _summary;
  bool _loading = true;
  late DateTime _selected; // first-of-month anchor

  String get _month => '${_selected.year.toString().padLeft(4, '0')}-${_selected.month.toString().padLeft(2, '0')}';

  /// 月份標題：一律在前端依 URL 語系（currentLng）組出來，不用後端的 month_label——
  /// 那是硬寫中文，非中文語系的醫師會看到中英混雜的標題。
  ///
  /// 走 t('…monthFormat') 而不是 intl 的 DateFormat.yM：月份寫法在五語系都已定義在
  /// 共用的 i18next JSON（React 端同一支 key），用同一份模板兩邊輸出才一致，
  /// 也不必依賴 intl locale data 是否已初始化。
  String get _monthLabel {
    // 舊版後端沒回 month_key → 退回本地選中的月份，標題不能因此壞掉
    final key = _summary?.month ?? _month;
    final parts = key.split('-');
    final year = parts.length == 2 ? int.tryParse(parts[0]) : null;
    final month = parts.length == 2 ? int.tryParse(parts[1]) : null;
    if (year == null || month == null) return key; // 非預期格式就原樣顯示
    return t('common.doctor.dashboard.monthFormat', args: {'year': year, 'month': month});
  }

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _selected = DateTime(now.year, now.month, 1);
    Future.microtask(_load);
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final s = await DashboardApi().getMonthlySummary(_month);
      if (mounted) setState(() { _summary = s; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _shiftMonth(int delta) {
    setState(() => _selected = DateTime(_selected.year, _selected.month + delta, 1));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final user = ref.watch(authProvider).user;
    final s = _summary;
    final name = user?.name ?? '';
    final redFlags = s?.totalRedFlagAlerts ?? 0;
    return Scaffold(
      appBar: AppBar(
        title: Text(t('common.appTitle')),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: t('common.header.logout'),
            onPressed: () => ref.read(authProvider.notifier).logout(),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          // ── 標題區：標題＋醫師名，一次講完，不再重複月份 ──
          Text(t('common.doctor.dashboard.title'),
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          if (name.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(name,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: tk.inkSecondary)),
          ],
          const SizedBox(height: 16),

          // ── 月份＋統計：步進器是卡片標題列，月份只在這裡出現 ──
          Card(
            child: Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
                child: Row(children: [
                  Expanded(
                    child: Text(_monthLabel,
                        style: Theme.of(context)
                            .textTheme
                            .titleMedium
                            ?.copyWith(fontWeight: FontWeight.w600, color: tk.inkHeading)),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    color: tk.inkSecondary,
                    tooltip: t('common.doctor.dashboard.prevMonth'),
                    onPressed: _loading ? null : () => _shiftMonth(-1),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    color: tk.inkSecondary,
                    tooltip: t('common.doctor.dashboard.nextMonth'),
                    onPressed: _loading ? null : () => _shiftMonth(1),
                  ),
                ]),
              ),
              Divider(height: 1, thickness: 1, color: tk.edge),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: _Stat(
                      label: t('common.doctor.dashboard.totalSessions'),
                      value: '${s?.totalSessions ?? 0}',
                      loading: _loading,
                    ),
                  ),
                  Container(width: 1, height: 48, color: tk.edge),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _Stat(
                      label: t('common.doctor.dashboard.redFlagMetric'),
                      value: '$redFlags',
                      loading: _loading,
                      // 語意色只給「真的有事」：紅旗 > 0 才上警示色，0 維持中性。
                      valueColor: redFlags > 0 ? tk.alertCritical : null,
                    ),
                  ),
                ]),
              ),
            ]),
          ),
          const SizedBox(height: 16),

          // ── 快速前往：分組列表列（同寬、可掃讀），取代散排藥丸鈕 ──
          _NavGroup(rows: [
            _NavRowSpec(Icons.group_outlined, t('dashboard.sidebar.nav.patients'), '/patients'),
            _NavRowSpec(Icons.description_outlined, t('dashboard.sidebar.nav.soapReports'), '/reports'),
            _NavRowSpec(Icons.bar_chart, t('dashboard.sidebar.nav.research'), '/research'),
          ]),

          // 醫師＝管理員（2026-08-22）：admin 工具列對醫師與管理員都顯示
          if ((user?.isAdmin ?? false) || (user?.isDoctor ?? false)) ...[
            const SizedBox(height: 20),
            Padding(
              padding: const EdgeInsets.only(left: 4, bottom: 8),
              child: Text(t('dashboard.sidebar.sections.admin'),
                  style: Theme.of(context)
                      .textTheme
                      .labelMedium
                      ?.copyWith(color: tk.inkMuted, letterSpacing: 0.5)),
            ),
            _NavGroup(rows: [
              _NavRowSpec(Icons.group_outlined, t('dashboard.sidebar.nav.userManagement'), '/admin/users'),
              _NavRowSpec(Icons.list_alt, t('dashboard.sidebar.nav.complaintTemplates'), '/admin/complaints'),
              _NavRowSpec(Icons.health_and_safety_outlined, t('dashboard.sidebar.nav.systemHealth'), '/admin/health'),
              _NavRowSpec(Icons.receipt_long, t('dashboard.sidebar.nav.auditLogs'), '/admin/audit-logs'),
            ]),
          ],
          const SizedBox(height: 20),
          if (s != null) ...[
            DonutCard(
              title: t('common.doctor.dashboard.chiefComplaintDistribution'),
              centerLabel: t('common.doctor.dashboard.sessions'),
              emptyLabel: t('common.doctor.dashboard.noCategoryData'),
              items: [for (final b in s.chiefComplaintDistribution) (label: _complaintLabel(b), count: b.count)],
            ),
            const SizedBox(height: 12),
            DailyTrendCard(
              title: t('common.doctor.dashboard.dailyTrend'),
              totalLabel: t('common.doctor.dashboard.totalSessions'),
              peakLabel: t('common.doctor.dashboard.peakDay'),
              days: [for (final day in s.dailyTrend) (label: day.label, sessions: day.sessions, redFlags: day.redFlags)],
            ),
          ],
        ],
      ),
    );
  }

  static const _complaintKey = {
    'hematuria': 'complaintHematuria',
    'frequency': 'complaintFrequency',
    'voiding': 'complaintVoiding',
    'pain': 'complaintPain',
    'other': 'complaintOther',
  };

  String _complaintLabel(BucketItem b) =>
      _complaintKey[b.key] != null ? t('common.doctor.dashboard.${_complaintKey[b.key]}') : b.label;
}

// ── 統計數字：標籤在上、數字在下；載入時放同形狀骨架而不是轉圈 ──
class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, required this.loading, this.valueColor});

  final String label;
  final String value;
  final bool loading;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tk.inkSecondary)),
      const SizedBox(height: 6),
      if (loading)
        Container(
          width: 56,
          height: 32,
          decoration: BoxDecoration(color: tk.edge, borderRadius: BorderRadius.circular(6)),
        )
      else
        Text(value,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: valueColor ?? tk.inkHeading,
                  fontFeatures: const [FontFeature.tabularFigures()],
                )),
    ]);
  }
}

class _NavRowSpec {
  const _NavRowSpec(this.icon, this.label, this.route);
  final IconData icon;
  final String label;
  final String route;
}

// ── 導航群組：一張卡、多列、hairline 分隔（分隔線縮排對齊文字起點）──
class _NavGroup extends StatelessWidget {
  const _NavGroup({required this.rows});

  final List<_NavRowSpec> rows;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Card(
      clipBehavior: Clip.antiAlias, // InkWell 水波不溢出圓角
      child: Column(children: [
        for (var i = 0; i < rows.length; i++) ...[
          if (i > 0)
            Divider(height: 1, thickness: 1, indent: 64, color: tk.edge),
          _ActionRow(spec: rows[i]),
        ],
      ]),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({required this.spec});

  final _NavRowSpec spec;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final primary = Theme.of(context).colorScheme.primary;
    return InkWell(
      onTap: () => context.go(prefixLngToPath(spec.route, currentLng)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: primary.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(spec.icon, size: 20, color: primary),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(spec.label,
                style: Theme.of(context)
                    .textTheme
                    .bodyLarge
                    ?.copyWith(color: tk.inkBody, fontWeight: FontWeight.w500)),
          ),
          Icon(Icons.chevron_right, size: 20, color: tk.inkMuted),
        ]),
      ),
    );
  }
}
