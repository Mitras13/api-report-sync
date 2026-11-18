-- آخرین نسخه‌ی هر نوبت همکده (۲۰۲۶-۱۱-۰۷)
--
-- از وقتی APT_RSV_HK (نوبت‌ها بر اساس «تاریخ نوبت»، پوشه‌ی raw_data/NobatDate/HK) هم در dbo.APT_LST_HK
-- بار می‌شود، یک [شناسه] می‌تواند چند ردیف داشته باشد (دانلود بر اساس تاریخ ثبت + دانلودهای بعد از روز
-- نوبت). آخرین نسخه = ردیفی که «زمان دانلود» (۱۴ رقم آخر نام فایل) بیشتری دارد. مقایسه‌ی کل _SourceFile
-- درست نیست، چون 'NobatDate/' همیشه از 'Nobat/' بزرگ‌تر است.
--
-- دو view قبلی که مستقیم جدول خام را می‌خواندند (و قبلاً یک ردیف برای هر نوبت می‌دیدند) حالا از
-- APT_LST_HK_Latest می‌خوانند، تا Power BI نوبت را دو بار نشمارد.
--
-- برگشت (تعریف قبلی):
--   CREATE OR ALTER VIEW dbo.vw_APT_LST_HK AS
--   SELECT [شناسه],[نام مشاور],[شماره مراجع],[زمینه تخصص],[موضوضع مشاوره],[تاریخ نوبت],[وضعیت نوبت],
--   [وضعیت مشاوره],[دلیل کنسلی],[شناسه نوبت جدید],[ثبت کننده],[نوع ثبت کننده],[تاریخ ثبت],
--   [به روزرسانی کننده],[تاریخ به روزرسانی],[خارج از تایم],[تاریخ لغو],[سرپرست مشاور],[تاریخ پرونده]
--   FROM dbo.APT_LST_HK;
--
--   CREATE OR ALTER VIEW dbo.Fact_Appointment_Hamkade AS
--   SELECT dt.ResultDate AS DateKey, a.*
--   FROM dbo.APT_LST_HK a
--   OUTER APPLY dbo.fn_JalaliToGregorian(a.[تاریخ ثبت]) dt;

CREATE OR ALTER VIEW dbo.APT_LST_HK_Latest AS
SELECT [_SourceFile],[شناسه],[نام مشاور],[شماره مراجع],[زمینه تخصص],[موضوضع مشاوره],[تاریخ نوبت],[وضعیت نوبت],
       [وضعیت مشاوره],[دلیل کنسلی],[شناسه نوبت جدید],[ثبت کننده],[نوع ثبت کننده],[تاریخ ثبت],
       [به روزرسانی کننده],[تاریخ به روزرسانی],[خارج از تایم],[تاریخ لغو],[سرپرست مشاور],[تاریخ پرونده],
       [موضوع مشاوره]
FROM (
    SELECT a.*,
           ROW_NUMBER() OVER (
               PARTITION BY a.[شناسه]
               ORDER BY LEFT(RIGHT(a.[_SourceFile], 22), 14) DESC, a.[_SourceFile] DESC
           ) AS rn
    FROM dbo.APT_LST_HK a
) x
WHERE rn = 1;
GO

CREATE OR ALTER VIEW dbo.vw_APT_LST_HK AS
SELECT [شناسه],[نام مشاور],[شماره مراجع],[زمینه تخصص],[موضوضع مشاوره],[تاریخ نوبت],[وضعیت نوبت],
[وضعیت مشاوره],[دلیل کنسلی],[شناسه نوبت جدید],[ثبت کننده],[نوع ثبت کننده],[تاریخ ثبت],
[به روزرسانی کننده],[تاریخ به روزرسانی],[خارج از تایم],[تاریخ لغو],[سرپرست مشاور],[تاریخ پرونده]
FROM dbo.APT_LST_HK_Latest;
GO

CREATE OR ALTER VIEW dbo.Fact_Appointment_Hamkade AS
SELECT dt.ResultDate AS DateKey, a.*
FROM dbo.APT_LST_HK_Latest a
OUTER APPLY dbo.fn_JalaliToGregorian(a.[تاریخ ثبت]) dt;
GO
