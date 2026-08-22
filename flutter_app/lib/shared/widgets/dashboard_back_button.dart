import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';

/// 儀表板區頁面（病患列表／SOAP 報告／研究分析／admin 四頁）AppBar 的返回鍵。
///
/// 這些頁面是頂層路由（2026-08-22 路由樹重構後不再巢在佔位頁下），Navigator
/// 無可 pop——返回語意是「回儀表板」（它們的入口都在儀表板的導航列），
/// 所以用 go() 而不是 pop()。頁面同時包在 DoctorShell(index:0) 裡，
/// 底部導覽也永遠在：這顆鍵是給「往左上找返回」的使用習慣一條明路。
class DashboardBackButton extends StatelessWidget {
  const DashboardBackButton({super.key});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.arrow_back),
      tooltip: t('dashboard.sidebar.nav.dashboard'),
      onPressed: () => context.go(prefixLngToPath('/dashboard', currentLng)),
    );
  }
}
