-- گزارش تبلیغات پنل هوشمند (SPA_54 و SPA_HK، downloaders/smart_panel_ads.py) برای داشبورد و هوش مصنوعی.
-- جدول خام دو سطح روی هم دارد: هر روز یک‌بار به تفکیک عاملیت و یک‌بار به تفکیک مسئول تبلیغات
-- (همان عددها، گروه‌بندی دیگر). جمع ساده‌ی جدول خام دو برابر است؛ از یکی از این دو view استفاده کن.
-- مبلغ‌ها (paid_factor، registered_factor) میلیون تومان.
DROP VIEW IF EXISTS dbo.SPA_54_ByAgency;
DROP VIEW IF EXISTS dbo.SPA_54_ByLeader;
GO

CREATE OR ALTER VIEW dbo.SPA_All_ByAgency AS
SELECT N'5040' AS Company, CAST(ReportDate AS date) AS ReportDate, ReportDateJalali, AAName AS Agency,
       number_entries, number_consume_calls, number_calls, number_answered, number_reach_answered,
       number_registered, number_paid, registered_factor, paid_factor, call_duration, target_number,
       CPC, answered_percent, bought_percent, paid_percent, rch_ans_percent, percent_target_number,
       paid_coe, money_coe, duration_coe, _SourceFile
FROM dbo.SPA_54
WHERE RowType = N'agency'
UNION ALL
SELECT N'همکده', CAST(ReportDate AS date), ReportDateJalali, AAName,
       number_entries, number_consume_calls, number_calls, number_answered, number_reach_answered,
       number_registered, number_paid, registered_factor, paid_factor, call_duration, target_number,
       CPC, answered_percent, bought_percent, paid_percent, rch_ans_percent, percent_target_number,
       paid_coe, money_coe, duration_coe, _SourceFile
FROM dbo.SPA_HK
WHERE RowType = N'agency';
GO

-- 5040: اسم مسئول در پنل پیشوند mahsul دارد (برداشته می‌شود) و AAName = N'0' گروه عاملیت‌های بدون مسئول است.
-- همکده: اسم مسئول بدون پیشوند است و ردیف «بدون مسئول» ندارد (سایت در هیچ مسئولی نیست).
CREATE OR ALTER VIEW dbo.SPA_All_ByLeader AS
SELECT N'5040' AS Company, CAST(ReportDate AS date) AS ReportDate, ReportDateJalali,
       CASE WHEN AAName = N'0' THEN N'بدون مسئول'
            WHEN AAName LIKE N'mahsul%' THEN SUBSTRING(AAName, 7, 200)
            ELSE AAName END AS Leader,
       number_entries, number_consume_calls, number_calls, number_answered, number_reach_answered,
       number_registered, number_paid, registered_factor, paid_factor, call_duration, target_number,
       CPC, answered_percent, bought_percent, paid_percent, rch_ans_percent, percent_target_number,
       paid_coe, money_coe, duration_coe, _SourceFile
FROM dbo.SPA_54
WHERE RowType = N'leader'
UNION ALL
SELECT N'همکده', CAST(ReportDate AS date), ReportDateJalali, AAName,
       number_entries, number_consume_calls, number_calls, number_answered, number_reach_answered,
       number_registered, number_paid, registered_factor, paid_factor, call_duration, target_number,
       CPC, answered_percent, bought_percent, paid_percent, rch_ans_percent, percent_target_number,
       paid_coe, money_coe, duration_coe, _SourceFile
FROM dbo.SPA_HK
WHERE RowType = N'leader';
GO
