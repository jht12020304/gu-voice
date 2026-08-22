import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/models/soap_report.dart';

// 醫師端報告列表每一列要顯示病患姓名、主訴與紅旗。這些欄位在 Session 上，過去是
// 拿到報告後再對每一列打一次 `GET /sessions/{id}`（一頁 20 列 ＝ 20 個額外請求，
// 而且清單先畫出一排 UUID 再逐筆補值重排）。後端 2026-08-22 起改成隨 `GET /reports`
// 一起回。
//
// 這裡釘住的是**部署順序**：TestFlight 上的 App 打的是生產後端，兩邊不會同時更新。
// 後端還沒帶這幾欄時 `hasSessionContext` 必須是 false，report_list_page 才會退回舊的
// 逐列補值路徑；若旗標判斷錯邊，症狀是整頁顯示 UUID 而且沒有任何錯誤訊息。
void main() {
  Map<String, dynamic> base() => {
        'id': 'r1',
        'sessionId': 's1',
        'status': 'generated',
        'reviewStatus': 'pending',
      };

  group('SoapReport 的場次上下文', () {
    test('舊後端（沒帶這幾欄）→ hasSessionContext false，欄位全 null', () {
      final r = SoapReport.fromJson(base());

      expect(r.hasSessionContext, isFalse);
      expect(r.patientName, isNull);
      expect(r.chiefComplaintText, isNull);
      expect(r.sessionStatus, isNull);
      expect(r.sessionRedFlag, isNull);
    });

    test('新後端 → 四欄都解得出來', () {
      final r = SoapReport.fromJson({
        ...base(),
        'patientName': '王小明',
        'chiefComplaintText': '血尿三天',
        'sessionStatus': 'completed',
        'sessionRedFlag': true,
      });

      expect(r.hasSessionContext, isTrue);
      expect(r.patientName, '王小明');
      expect(r.chiefComplaintText, '血尿三天');
      expect(r.sessionStatus, 'completed');
      expect(r.sessionRedFlag, isTrue);
    });

    test('沒有姓名的病患仍算「後端有帶」——旗標不看 patientName', () {
      // 匿名／未填姓名是合法資料。若用 patientName 當旗標，這些場次會永遠走
      // 每列一次請求的退路，也就是這次修掉的那個 N+1 又回來，而且只在部分列上。
      final r = SoapReport.fromJson({
        ...base(),
        'patientName': null,
        'chiefComplaintText': '頻尿',
        'sessionStatus': 'in_progress',
        'sessionRedFlag': false,
      });

      expect(r.hasSessionContext, isTrue);
      expect(r.patientName, isNull);
      expect(r.sessionRedFlag, isFalse);
    });

    test('紅旗是三態：null（不知道）不得被當成 false（沒紅旗）', () {
      // 呼叫端要自己決定退路。模型層把「後端沒說」壓成 false 等於對醫師宣告
      // 這個場次沒有紅旗，而那是這份 App 裡最不能說錯的一句話。
      expect(SoapReport.fromJson(base()).sessionRedFlag, isNull);
      expect(SoapReport.fromJson({...base(), 'sessionRedFlag': false}).sessionRedFlag, isFalse);
    });

    test('型別不對時不炸掉整頁（後端回了非預期形狀）', () {
      final r = SoapReport.fromJson({
        ...base(),
        'patientName': 123,
        'sessionRedFlag': 'true',
      });

      expect(r.patientName, isNull);
      expect(r.sessionRedFlag, isNull);
    });
  });
}
