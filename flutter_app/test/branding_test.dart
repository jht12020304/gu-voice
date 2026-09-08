import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

const _languages = ['zh-TW', 'en-US', 'ja-JP', 'ko-KR', 'vi-VN'];

File _file(String relative) => File('${Directory.current.path}/$relative');

void main() {
  test(
    'all Flutter locales expose the UroSense brand and compact guidance count',
    () {
      for (final language in _languages) {
        final common =
            json.decode(
                  _file(
                    'assets/locales/$language/common.json',
                  ).readAsStringSync(),
                )
                as Map<String, dynamic>;
        final conversation =
            json.decode(
                  _file(
                    'assets/locales/$language/conversation.json',
                  ).readAsStringSync(),
                )
                as Map<String, dynamic>;

        expect(
          common['appTitle'],
          'UroSense',
          reason: '$language appTitle 未統一',
        );
        final supervisor = conversation['supervisor'] as Map<String, dynamic>;
        expect(
          (supervisor['remainingCount'] as String?)?.trim(),
          isNotEmpty,
          reason: '$language 缺鍵盤縮排用的 remainingCount 文案',
        );
        expect(
          supervisor['remainingCount'],
          contains('{{count}}'),
          reason: '$language remainingCount 遺失 count 佔位符',
        );
      }
    },
  );

  test(
    'visible platform names are UroSense while technical identities stay stable',
    () {
      final app = _file('lib/app.dart').readAsStringSync();
      final ios = _file('ios/Runner/Info.plist').readAsStringSync();
      final android = _file(
        'android/app/src/main/AndroidManifest.xml',
      ).readAsStringSync();
      final web = _file('web/index.html').readAsStringSync();
      final manifest =
          json.decode(_file('web/manifest.json').readAsStringSync())
              as Map<String, dynamic>;
      final pubspec = _file('pubspec.yaml').readAsStringSync();

      expect(RegExp("title: 'UroSense'").allMatches(app), hasLength(2));
      expect(
        ios,
        contains('<key>CFBundleDisplayName</key>\n\t<string>UroSense</string>'),
      );
      expect(android, contains('android:label="UroSense"'));
      expect(
        web,
        contains('<meta name="apple-mobile-web-app-title" content="UroSense">'),
      );
      expect(web, contains('<div class="name">UroSense</div>'));
      expect(manifest['short_name'], 'UroSense');

      expect(
        pubspec,
        contains('name: gu_voice'),
        reason: '品牌改名不得重命名 Dart package，否則全專案 import 都會失效',
      );
      expect(
        ios,
        contains(r'$(PRODUCT_BUNDLE_IDENTIFIER)'),
        reason: '品牌改名不得把既有 bundle ID 改成新的 App 身分',
      );
      expect(
        _file('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync(),
        contains('PRODUCT_BUNDLE_IDENTIFIER = com.guvoice.guVoice;'),
      );
    },
  );

  test('provided mascot is registered as a non-empty Flutter asset', () {
    final mascot = _file('assets/images/urosense_mascot.png');
    expect(mascot.existsSync(), isTrue);
    expect(mascot.lengthSync(), greaterThan(0));
    expect(
      _file('pubspec.yaml').readAsStringSync(),
      contains('- assets/images/'),
    );
  });
}
