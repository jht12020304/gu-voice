import 'package:flutter/material.dart';

import '../../core/i18n/loc.dart';
import '../../core/theme/app_tokens.dart';

// Session status -> semantic color + i18n label (common.patient.home.status* keys).
// The `common.` namespace prefix is required: t() treats the first dot-segment as the
// namespace, so a bare `patient.…` key resolves to nothing and renders the raw key.
class StatusBadge extends StatelessWidget {
  const StatusBadge(this.status, {super.key});
  final String status;

  static const _labelKey = {
    'completed': 'common.patient.home.statusCompleted',
    'in_progress': 'common.patient.home.statusInProgress',
    'waiting': 'common.patient.home.statusWaiting',
    'aborted_red_flag': 'common.patient.home.statusAbortedRedFlag',
    'cancelled': 'common.patient.home.statusCancelled',
  };

  Color _color(AppTokens tk) {
    switch (status) {
      case 'completed':
        return tk.statusCompleted;
      case 'in_progress':
        return tk.statusInProgress;
      case 'waiting':
        return tk.statusWaiting;
      case 'aborted_red_flag':
        return tk.statusRedFlag;
      case 'cancelled':
        return tk.statusCancelled;
      default:
        return tk.statusCompleted; // unknown -> completed style (matches web fallback)
    }
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final color = _color(tk);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(9999),
      ),
      child: Text(
        t(_labelKey[status] ?? 'common.patient.home.statusCompleted'),
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}
