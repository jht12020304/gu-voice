import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/features/voice/state/settings_notifier.dart';

void main() {
  test('字體可放大，且限制在不破壞版面的 100%–140%', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final notifier = container.read(settingsProvider.notifier);

    notifier.setTextScale(1.2);
    expect(container.read(settingsProvider).textScale, 1.2);

    notifier.setTextScale(2);
    expect(container.read(settingsProvider).textScale, 1.4);
  });
}
