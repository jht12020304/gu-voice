import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_tokens.dart';
import '../../data/models/session.dart';
import '../../shared/format.dart';
import '../../shared/widgets/status_badge.dart';
import '../../shared/widgets/ui_kit.dart';

/// 病患端點開自己的場次：完成／紅旗中止 → 完成頁；進行中／等待 → 對話頁。
/// cancelled / unknown 不導頁（與 web 一致）。病患首頁與歷史頁共用。
void openPatientSession(BuildContext context, Session s) {
  if (s.status == 'completed' || s.status == 'aborted_red_flag') {
    context.go(prefixLngToPath('/patient/session/${s.id}/complete', currentLng));
  } else if (s.status == 'in_progress' || s.status == 'waiting') {
    context.go(prefixLngToPath('/conversation/${s.id}', currentLng), extra: s);
  }
}

/// 病患端場次列（首頁最近 5 筆／歷史頁清單同一顆）。
/// [durationKey] 由頁面帶自己既有的 i18n key（兩頁的 key 不同、文案相同）。
class PatientSessionTile extends StatelessWidget {
  const PatientSessionTile(this.session, {super.key, required this.durationKey});

  final Session session;
  final String durationKey;

  @override
  Widget build(BuildContext context) {
    final s = session;
    final redFlagColor = Theme.of(context).extension<AppTokens>()!.statusRedFlag;
    final duration = s.durationSeconds != null
        ? ' · ${t(durationKey, args: {'minutes': durationMinutes(s.durationSeconds)})}'
        : '';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        onTap: () => openPatientSession(context, s),
        leading: s.redFlag ? IconTile(Icons.flag, color: redFlagColor) : null,
        title: Text(s.chiefComplaintText ?? t('common.patient.home.defaultComplaint')),
        subtitle: Text('${formatDateTime(s.createdAt)}$duration'),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [StatusBadge(s.status), const SizedBox(width: 4), const Icon(Icons.chevron_right)],
        ),
      ),
    );
  }
}
