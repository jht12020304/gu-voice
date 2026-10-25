import 'package:flutter/material.dart';

/// 全 App 共用的 SnackBar 提示（取代各頁自抄的 `_toast`／inline showSnackBar）。
/// await 之後呼叫也安全：context 已卸載就靜默略過。
void showToast(BuildContext context, String message, {Duration? duration}) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message), duration: duration ?? const Duration(milliseconds: 4000)),
  );
}
