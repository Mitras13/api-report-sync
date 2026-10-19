/* ════════════════════════════════════════════════════════════════════════════════
   پاک‌سازی کپیِ اشتباه‌نامِ گزارش کارشناسان همکده در dbo.SaleR_HK (تهیه: ۱۴۰۵/۰۷/۲۷)
   ════════════════════════════════════════════════════════════════════════════════
   مشکل: ۸۴۷ فایل گزارش کارشناسان همکده با اسم فاکتور (INV_SAL/HK/HK_INV_SAL_…) ذخیره و در SaleR_HK لود شده‌اند
   (۴۸۰٬۷۵۶ ردیف، ۱ فروردین ۱۴۰۳ تا ۲۲ تیر ۱۴۰۵). بررسی ۱۴۰۵/۰۷/۲۷: همان ستون‌ها، همه‌ی ۸۴۵ روز در فایل‌های
   درست‌نام (…/HK_SaleR_…) هم هست، ۸۴۴ روز با وصول کل و کارتابلی دقیقاً برابر (۸ فروردین ۱۴۰۴ دو نسخه داشت).
   → کپی تکراری‌اند؛ هر گزارشی که SaleR_HK را بدون فیلتر اسم فایل جمع بزند آن روزها را دو برابر می‌بیند.

   فقط جدول dbo.SaleR_HK، فقط ردیف‌هایی که _SourceFile آن‌ها با «INV_SAL/» شروع می‌شود.

   ایمنی:
   - پیش‌فرض فقط «نمایش» است (ROLLBACK). اجرای واقعی: python scripts/run_cleanup.py cleanup_saler_hk_misnamed.sql
   - قبل از حذف، ردیف‌ها در dbo._bak_misnamed_SaleR_HK_14050727 کپی می‌شوند (برگشت‌پذیر).
   - اگر روزی از ردیف‌های حذفی در فایل‌های درست‌نام نباشد، یا تعداد ردیف حذف‌شده با انتظار نخواند، کل کار برمی‌گردد.
   - dbo.LoadedFiles و بقیه‌ی جدول‌ها دست نمی‌خورند.
   اجرا با حساب ویندوزی که حق نوشتن دارد؛ بارگذار شبانه در حال اجرا نباشد.

   برگشت (فقط اگر لازم شد): INSERT INTO dbo.SaleR_HK SELECT * FROM dbo._bak_misnamed_SaleR_HK_14050727;
   ════════════════════════════════════════════════════════════════════════════════ */
USE [Mitra_sarkhosh];
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @apply bit = 0;              -- ← 0 = فقط نمایش (ROLLBACK)؛ 1 = اجرای واقعی (COMMIT)
DECLARE @expected_rows int = 480756;
DECLARE @expected_files int = 847;

IF OBJECT_ID(N'dbo._bak_misnamed_SaleR_HK_14050727') IS NOT NULL
    THROW 50011, N'جدول پشتیبان از قبل هست — این پاک‌سازی قبلاً انجام شده است.', 1;

-- هر روزِ ردیف‌های اشتباه‌نام باید در فایل‌های درست‌نام هم باشد (وگرنه داده‌ی آن روز گم می‌شد)
IF EXISTS (
    SELECT 1 FROM (SELECT DISTINCT SUBSTRING(_SourceFile, CHARINDEX('_INV_SAL_', _SourceFile) + 9, 8) AS d
                   FROM dbo.SaleR_HK WHERE _SourceFile LIKE N'INV[_]SAL/%') m
    WHERE NOT EXISTS (SELECT 1 FROM dbo.SaleR_HK s
                      WHERE s._SourceFile LIKE N'SaleR/HK/HK[_]SaleR[_]' + m.d + N'%'))
    THROW 50012, N'روزی هست که فقط در فایل‌های اشتباه‌نام وجود دارد — کار انجام نشد.', 1;

DECLARE @files int = (SELECT COUNT(DISTINCT _SourceFile) FROM dbo.SaleR_HK WHERE _SourceFile LIKE N'INV[_]SAL/%');
DECLARE @before int = (SELECT COUNT(*) FROM dbo.SaleR_HK);

BEGIN TRANSACTION;

SELECT * INTO dbo._bak_misnamed_SaleR_HK_14050727 FROM dbo.SaleR_HK WHERE _SourceFile LIKE N'INV[_]SAL/%';
DELETE FROM dbo.SaleR_HK WHERE _SourceFile LIKE N'INV[_]SAL/%';
DECLARE @deleted int = @@ROWCOUNT;

IF @deleted <> @expected_rows OR @files <> @expected_files
    THROW 50013, N'تعداد ردیف یا فایل با انتظار نمی‌خواند — کار برگشت خورد.', 1;

SELECT N'SaleR_HK' AS [جدول], @files AS [فایل], @deleted AS [ردیف حذف‌شده], @expected_rows AS [انتظار],
       @before AS [ردیف قبل], (SELECT COUNT(*) FROM dbo.SaleR_HK) AS [ردیف بعد];

IF @apply = 1
BEGIN
    COMMIT TRANSACTION;
    PRINT N'✓ انجام شد. پشتیبان: dbo._bak_misnamed_SaleR_HK_14050727';
END
ELSE
BEGIN
    ROLLBACK TRANSACTION;
    PRINT N'فقط نمایش بود؛ هیچ تغییری نماند. برای اجرای واقعی @apply = 1.';
END
