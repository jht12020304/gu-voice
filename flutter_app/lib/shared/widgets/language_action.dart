import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/i18n/locales_loader.dart';
import '../../core/router/lng.dart';
import '../../data/api/sessions_api.dart';

/// 目前路徑若停在「進行中的問診」，回傳該場次 id，否則 null。
///
/// 抽成純函式是因為這個判斷錯哪一邊都有代價：漏判 → 切語言把場次丟在
/// in_progress（孤兒，後端還在用舊語言跑）；誤判 → 在不相干的頁面把使用者
/// 擋在確認框前。比對方式是「拿掉 lng 後剛好是 `conversation/:id` 兩段」，
/// 而不是 `contains('/conversation')`——後者會誤傷 /patient/conversations-archive
/// 這類路徑（同一個坑在 kiosk_idle_guard 的測試裡也擋過一次）。
String? conversationSessionIdInPath(String path) {
  final parts = stripLngFromPath(path).split('/').where((s) => s.isNotEmpty).toList();
  if (parts.length != 2 || parts.first != 'conversation') return null;
  return parts[1];
}

/// 切語言的單一入口（`LanguageAction` 與 `LanguageBar` 共用）。
///
/// URL 是語言的唯一權威，所以切換＝把同一個 URI 換上新的 lng 前綴（保留整段
/// URI，query 不會被吃掉）。唯一的例外是停在問診頁時：後端場次是綁著語言在跑
/// 的，直接導走會留下孤兒 in_progress 場次，所以先取得病患同意、呼叫
/// `POST /sessions/{id}/end-for-language-switch` 收掉場次，**成功才導頁**。
Future<void> switchLanguage(BuildContext context, String lng) async {
  // Router / messenger 都在 await 之前取好，之後就不必再碰可能已失效的 context。
  final router = GoRouter.of(context);
  final messenger = ScaffoldMessenger.maybeOf(context);
  final uri = GoRouterState.of(context).uri;
  final target = uri.replace(path: prefixLngToPath(uri.path, lng)).toString();

  // 已經是這個語言就什麼都不做。重導同一個 URL 會重建整頁——在問診頁等於把
  // autoDispose 的 conversation controller 砍掉重來，病患的場次就這樣沒了。
  if (target == uri.toString()) return;

  final sessionId = conversationSessionIdInPath(uri.path);
  if (sessionId == null) {
    // Boot loads only the active language plus its fallback chain; the rest are warmed
    // in the background after the first frame. On a fast tap the target may not be
    // resident yet, and the new page would render the zh-TW fallback and then visibly
    // re-render. Already-loaded is a no-op, so the normal case costs nothing.
    // Placed immediately before the navigation, not at the top: an await in front of
    // the `showDialog(context: ...)` below would use a BuildContext across an async gap.
    await Locales.ensure(lng);
    router.go(target);
    return;
  }

  final outcome = await showDialog<bool>(
    context: context,
    // 誤觸背景不該悄悄取消，更重要的是 API 在途時不能讓視窗被關掉。
    barrierDismissible: false,
    builder: (_) => _EndSessionForSwitchDialog(sessionId: sessionId, toLng: lng),
  );
  if (outcome == null) return; // 使用者取消，語言不動

  if (outcome) {
    // Same reason as the branch above — and here the snackbar below also renders with
    // `lng:` forced to the target, so its strings have to be resident too.
    await Locales.ensure(lng);
    // 場次剛被後端轉成 cancelled，所以**不能**回同一條 `conversation/:id`——那條路由
    // `_lngKeyed` 會重建 ConversationPage，`_init` 又對一場 cancelled 場次呼叫 start()
    // （WS 授權失敗 / 錯誤橫幅）。導回該語言的病患首頁，病患可直接用新語言重開一場，
    // 也正是確認框文案（switchModal.description）承諾的下一步。
    router.go(prefixLngToPath('/patient', lng));
    // 導頁後畫面已是新語言，提示也用新語言；失敗時畫面沒變，維持原語言。
    messenger?.showSnackBar(SnackBar(
      content: Text(t(
        'common.language.switchModal.switchedEnded',
        args: {'name': t('common.language.names.$lng', lng: lng)},
        lng: lng,
      )),
    ));
    return;
  }

  // 端點失敗絕不默默切語言：場次會留在 in_progress，病患和現場醫護都不會知道
  // 剛剛發生了什麼事。錯誤要看得見，文案也要告訴病患下一步能做什麼。
  messenger?.showSnackBar(SnackBar(
    content: Text(t('common.language.switchModal.switchFailed')),
  ));
}

/// 結束場次的確認框。API 呼叫放在框內，是為了讓按鈕能顯示「切換中…」並在
/// 途中禁用——否則連點會打出多次 end-for-language-switch。
class _EndSessionForSwitchDialog extends StatefulWidget {
  const _EndSessionForSwitchDialog({required this.sessionId, required this.toLng});

  final String sessionId;
  final String toLng;

  @override
  State<_EndSessionForSwitchDialog> createState() => _EndSessionForSwitchDialogState();
}

class _EndSessionForSwitchDialogState extends State<_EndSessionForSwitchDialog> {
  bool _busy = false;

  // pop(true) = 場次已收掉、可以切；pop(false) = 端點失敗；pop(null) = 使用者取消。
  Future<void> _confirm() async {
    setState(() => _busy = true);
    try {
      await SessionsApi().endSessionForLanguageSwitch(widget.sessionId, widget.toLng);
      if (mounted) Navigator.of(context).pop(true);
    } catch (_) {
      if (mounted) Navigator.of(context).pop(false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // API 在途時擋掉返回鍵：關掉視窗就沒人知道場次到底收掉了沒。
      canPop: !_busy,
      child: AlertDialog(
        title: Text(t('common.language.switchModal.title')),
        content: Text(t('common.language.switchModal.description', args: {
          'from': t('common.language.names.$currentLng'),
          'to': t('common.language.names.${widget.toLng}'),
        })),
        actions: [
          TextButton(
            onPressed: _busy ? null : () => Navigator.of(context).pop(),
            child: Text(t('common.language.switchModal.cancel')),
          ),
          FilledButton(
            onPressed: _busy ? null : _confirm,
            child: Text(t(_busy
                ? 'common.language.switchModal.switching'
                : 'common.language.switchModal.confirm')),
          ),
        ],
      ),
    );
  }
}

/// Compact language switcher for an `AppBar`'s `actions`.
///
/// `LanguageBar` (the chip row) only appeared on 4 screens, so a patient who ended up in
/// the wrong language anywhere else had no way to change it (TODO §G medium). This is the
/// same authority — navigate to the current URI under a new lng, whole URI preserved so
/// query params survive.
///
/// 停在 `/conversation/:id` 時 `switchLanguage` 會先跳確認框、呼叫
/// `POST /sessions/{id}/end-for-language-switch` 收掉場次，成功才導頁，所以放在問診頁
/// 也不會留下孤兒 `in_progress` 場次。
///
/// 2026-08-18（臨床拍板，G34/G35b）：**已掛進 `ConversationPage` 的 AppBar**。
/// 走錯語言的病患一旦進了問診頁就再也換不掉，是比「多一個誤觸入口」更重的缺陷；
/// 確認框本身就是誤觸的防線（barrierDismissible: false，取消＝什麼都不做，
/// 場次與 WS 完全不受影響）。React 端的對應入口是 `ConversationPage.tsx` 頁首的
/// `<LanguageSwitcher />`，兩端行為一致：確認後 REST 成功才導回該語言的病患首頁。
class LanguageAction extends StatelessWidget {
  const LanguageAction({super.key});

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.language),
      tooltip: t('common.language.names.$currentLng'),
      // Router state is read at TAP time, not during build. Reading it in build makes the
      // widget unusable anywhere without a GoRouter ancestor — which broke the intake
      // widget tests, and is the same shape as the G11 crash
      // (`GoRouterState.of` above the Navigator). Same lesson: read it where it is needed.
      onSelected: (lng) => switchLanguage(context, lng),
      itemBuilder: (context) => [
        for (final lng in supportedLanguages)
          PopupMenuItem(
            value: lng,
            child: Row(children: [
              if (lng == currentLng) ...[
                const Icon(Icons.check, size: 16),
                const SizedBox(width: 6),
              ],
              Text(t('common.language.names.$lng') +
                  (betaLanguages.contains(lng) ? ' ${t('common.language.betaTag')}' : '')),
            ]),
          ),
      ],
    );
  }
}
