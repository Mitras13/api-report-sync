/* ════════════════════════════════════════════════════════════════════════════════
   پاک‌سازی یک‌باره‌ی فایل‌های دوباره‌دانلودشده (تهیه: ۱۴۰۵/۰۷/۲۷)
   ════════════════════════════════════════════════════════════════════════════════
   مشکل: ربات بعضی بازه‌ها را دوباره دانلود کرده (اسم فایل فقط در «زمان دانلود» فرق دارد) و بارگذار هر دو را وارد
   کرده → آن روزها دو بار شمرده می‌شوند (مثلاً وصول 5040 خرداد ۱۴۰۵: ۱۸۷٬۰۶۲ به‌جای ۱۷۷٬۵۰۱).
   این اسکریپت از هر بازه فقط آخرین دانلود را نگه می‌دارد: 40 فایل قدیمی، 198,304 ردیف.

   ایمنی:
   - پیش‌فرض فقط «نمایش» است: همه‌چیز اجرا و شمرده می‌شود و آخر ROLLBACK (هیچ تغییری نمی‌ماند).
     برای اجرای واقعی، بعد از دیدن نتیجه، @apply را 1 کنید و دوباره اجرا کنید.
   - قبل از حذف، ردیف‌های حذفی در جدول‌های پشتیبان dbo._bak_dup_<جدول>_14050727 کپی می‌شوند (برگشت‌پذیر).
   - همه در یک تراکنش؛ اگر تعداد ردیف حذف‌شده‌ی هر جدول با انتظار نخواند، یا نسخه‌ی جدید یک فایل در جدول نباشد،
     کل کار برمی‌گردد.
   - فایل‌های قدیمی در dbo.LoadedFiles می‌مانند با [RowCount] = 0 تا بارگذار دوباره واردشان نکند.
   - دو نیمه‌ی یک روز (همکده ۳۰ اسفند ۱۴۰۳: 00:00–12:31 و 12:31–23:59) تکراری نیستند و در فهرست نیستند.
   اجرا: SSMS با حساب ویندوزی که روی Mitra_sarkhosh حق نوشتن دارد (نه PowerBI_Reader).
   قبل از اجرا: بارگذار شبانه (load_raw_data_to_sql.py) در حال اجرا نباشد.

   برگشت (فقط اگر لازم شد، بعد از @apply = 1):
     INSERT INTO dbo.[SaleR_54] SELECT * FROM dbo.[_bak_dup_SaleR_54_14050727];   -- و همین برای بقیه‌ی جدول‌ها
     UPDATE dbo.LoadedFiles SET [RowCount] = b.n FROM dbo.LoadedFiles f
       JOIN (SELECT _SourceFile, COUNT(*) n FROM dbo.[_bak_dup_SaleR_54_14050727] GROUP BY _SourceFile) b
         ON b._SourceFile = f.RelativePath;
   ════════════════════════════════════════════════════════════════════════════════ */
USE [Mitra_sarkhosh];
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @apply bit = 0;   -- ← 0 = فقط نمایش (ROLLBACK)؛ 1 = اجرای واقعی (COMMIT)

DECLARE @files TABLE (TableName sysname, OldFile nvarchar(400), NewFile nvarchar(400), ExpectedRows int);
INSERT INTO @files (TableName, OldFile, NewFile, ExpectedRows) VALUES
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030101000000_14030101235959_14050616093958.parquet', N'SaleR/54/54_SaleR_14030101000000_14030101235959_14050616124600.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030102000000_14030102235959_14050616094235.parquet', N'SaleR/54/54_SaleR_14030102000000_14030102235959_14050616124916.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030103000000_14030103235959_14050616094504.parquet', N'SaleR/54/54_SaleR_14030103000000_14030103235959_14050616125135.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030104000000_14030104235959_14050616094733.parquet', N'SaleR/54/54_SaleR_14030104000000_14030104235959_14050616125420.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030105000000_14030105235959_14050616095043.parquet', N'SaleR/54/54_SaleR_14030105000000_14030105235959_14050616125733.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030106000000_14030106235959_14050616095534.parquet', N'SaleR/54/54_SaleR_14030106000000_14030106235959_14050616130025.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030107000000_14030107235959_14050616095838.parquet', N'SaleR/54/54_SaleR_14030107000000_14030107235959_14050616130348.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030108000000_14030108235959_14050616100218.parquet', N'SaleR/54/54_SaleR_14030108000000_14030108235959_14050616130717.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030109000000_14030109235959_14050616100513.parquet', N'SaleR/54/54_SaleR_14030109000000_14030109235959_14050616131034.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030110000000_14030110235959_14050616100832.parquet', N'SaleR/54/54_SaleR_14030110000000_14030110235959_14050616131319.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030111000000_14030111235959_14050616101124.parquet', N'SaleR/54/54_SaleR_14030111000000_14030111235959_14050616131835.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030112000000_14030112235959_14050616101423.parquet', N'SaleR/54/54_SaleR_14030112000000_14030112235959_14050616132153.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030113000000_14030113235959_14050616101643.parquet', N'SaleR/54/54_SaleR_14030113000000_14030113235959_14050616132448.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030114000000_14030114235959_14050616102409.parquet', N'SaleR/54/54_SaleR_14030114000000_14030114235959_14050616133217.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030115000000_14030115235959_14050616102728.parquet', N'SaleR/54/54_SaleR_14030115000000_14030115235959_14050616133536.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030116000000_14030116235959_14050616103230.parquet', N'SaleR/54/54_SaleR_14030116000000_14030116235959_14050616133838.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030117000000_14030117235959_14050616103550.parquet', N'SaleR/54/54_SaleR_14030117000000_14030117235959_14050616134123.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030118000000_14030118235959_14050616104337.parquet', N'SaleR/54/54_SaleR_14030118000000_14030118235959_14050616134916.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030119000000_14030119235959_14050616105125.parquet', N'SaleR/54/54_SaleR_14030119000000_14030119235959_14050616135642.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030120000000_14030120235959_14050616105853.parquet', N'SaleR/54/54_SaleR_14030120000000_14030120235959_14050616140417.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030121000000_14030121235959_14050616110625.parquet', N'SaleR/54/54_SaleR_14030121000000_14030121235959_14050616141152.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030122000000_14030122235959_14050616111339.parquet', N'SaleR/54/54_SaleR_14030122000000_14030122235959_14050616141456.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030123000000_14030123235959_14050616111646.parquet', N'SaleR/54/54_SaleR_14030123000000_14030123235959_14050616141818.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030124000000_14030124235959_14050616111921.parquet', N'SaleR/54/54_SaleR_14030124000000_14030124235959_14050616142113.parquet', 5336),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030205000000_14030205235959_14050616142610.parquet', N'SaleR/54/54_SaleR_14030205000000_14030205235959_14050616172017.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030206000000_14030206235959_14050616142658.parquet', N'SaleR/54/54_SaleR_14030206000000_14030206235959_14050616172107.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030207000000_14030207235959_14050616142802.parquet', N'SaleR/54/54_SaleR_14030207000000_14030207235959_14050616172215.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030208000000_14030208235959_14050616142900.parquet', N'SaleR/54/54_SaleR_14030208000000_14030208235959_14050616172325.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030209000000_14030209235959_14050616143008.parquet', N'SaleR/54/54_SaleR_14030209000000_14030209235959_14050616172425.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030210000000_14030210235959_14050616143103.parquet', N'SaleR/54/54_SaleR_14030210000000_14030210235959_14050616172518.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030211000000_14030211235959_14050616143154.parquet', N'SaleR/54/54_SaleR_14030211000000_14030211235959_14050616172631.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030212000000_14030212235959_14050616143304.parquet', N'SaleR/54/54_SaleR_14030212000000_14030212235959_14050616172726.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030213000000_14030213235959_14050616143414.parquet', N'SaleR/54/54_SaleR_14030213000000_14030213235959_14050616172833.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030214000000_14030214235959_14050616143501.parquet', N'SaleR/54/54_SaleR_14030214000000_14030214235959_14050616172939.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030215000000_14030215235959_14050616143548.parquet', N'SaleR/54/54_SaleR_14030215000000_14030215235959_14050616173027.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14030216000000_14030216235959_14050616143700.parquet', N'SaleR/54/54_SaleR_14030216000000_14030216235959_14050616173119.parquet', 5338),
    (N'SaleR_54', N'SaleR/54/54_SaleR_14050330000000_14050330235959_14050618103953.parquet', N'SaleR/54/54_SaleR_14050330000000_14050330235959_14050618113206.parquet', 5349),
    (N'SaleR_HK', N'SaleR/HK/HK_SaleR_14040108000000_14040108235959_14050603140028.parquet', N'SaleR/HK/HK_SaleR_14040108000000_14040108235959_14050603141916.parquet', 570),
    (N'INV_SAL_54', N'INV_SAL/54/54_INV_SAL_14040108000000_14040108235959_14050603140121.parquet', N'INV_SAL/54/54_INV_SAL_14040108000000_14040108235959_14050603142007.parquet', 239),
    (N'INV_SAL_HK', N'INV_SAL/HK/HK_INV_SAL_14030102000000_14030102235959_14050614163910.parquet', N'INV_SAL/HK/HK_INV_SAL_14030102000000_14030102235959_14050614164104.parquet', 26);

DECLARE @result TABLE (TableName sysname, Deleted int, Expected int);

-- جدول پشتیبان از قبل هست؟ (یعنی اسکریپت یک بار با @apply = 1 اجرا شده)
IF OBJECT_ID(N'dbo._bak_dup_SaleR_54_14050727') IS NOT NULL
    THROW 50001, N'جدول پشتیبان از قبل هست — این پاک‌سازی قبلاً انجام شده است.', 1;

BEGIN TRANSACTION;

-- ── SaleR_54 ──
SELECT d.* INTO dbo.[_bak_dup_SaleR_54_14050727] FROM dbo.[SaleR_54] d
WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'SaleR_54');
DELETE d FROM dbo.[SaleR_54] d WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'SaleR_54');
INSERT INTO @result SELECT N'SaleR_54', @@ROWCOUNT, (SELECT SUM(ExpectedRows) FROM @files WHERE TableName = N'SaleR_54');
-- ── SaleR_HK ──
SELECT d.* INTO dbo.[_bak_dup_SaleR_HK_14050727] FROM dbo.[SaleR_HK] d
WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'SaleR_HK');
DELETE d FROM dbo.[SaleR_HK] d WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'SaleR_HK');
INSERT INTO @result SELECT N'SaleR_HK', @@ROWCOUNT, (SELECT SUM(ExpectedRows) FROM @files WHERE TableName = N'SaleR_HK');
-- ── INV_SAL_54 ──
SELECT d.* INTO dbo.[_bak_dup_INV_SAL_54_14050727] FROM dbo.[INV_SAL_54] d
WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'INV_SAL_54');
DELETE d FROM dbo.[INV_SAL_54] d WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'INV_SAL_54');
INSERT INTO @result SELECT N'INV_SAL_54', @@ROWCOUNT, (SELECT SUM(ExpectedRows) FROM @files WHERE TableName = N'INV_SAL_54');
-- ── INV_SAL_HK ──
SELECT d.* INTO dbo.[_bak_dup_INV_SAL_HK_14050727] FROM dbo.[INV_SAL_HK] d
WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'INV_SAL_HK');
DELETE d FROM dbo.[INV_SAL_HK] d WHERE d.[_SourceFile] IN (SELECT OldFile FROM @files WHERE TableName = N'INV_SAL_HK');
INSERT INTO @result SELECT N'INV_SAL_HK', @@ROWCOUNT, (SELECT SUM(ExpectedRows) FROM @files WHERE TableName = N'INV_SAL_HK');

-- نسخه‌ی جدید هر فایل باید در جدولش باشد (وگرنه آن بازه کامل حذف می‌شد)
IF EXISTS (SELECT 1 FROM @files f WHERE NOT EXISTS (SELECT 1 FROM dbo.LoadedFiles l WHERE l.RelativePath = f.NewFile AND l.[RowCount] > 0))
    THROW 50002, N'نسخه‌ی جدید یکی از فایل‌ها بارگذاری نشده — کار برگشت خورد.', 1;
IF EXISTS (SELECT 1 FROM @result WHERE Deleted <> Expected)
    THROW 50003, N'تعداد ردیف حذف‌شده با انتظار نمی‌خواند — کار برگشت خورد.', 1;

UPDATE l SET [RowCount] = 0 FROM dbo.LoadedFiles l JOIN @files f ON f.OldFile = l.RelativePath;

SELECT TableName AS [جدول], Deleted AS [ردیف حذف‌شده], Expected AS [انتظار] FROM @result;
SELECT COUNT(*) AS [فایل], SUM(ExpectedRows) AS [ردیف] FROM @files;

IF @apply = 1
BEGIN
    COMMIT TRANSACTION;
    PRINT N'✓ انجام شد. پشتیبان‌ها: dbo._bak_dup_*_14050727';
END
ELSE
BEGIN
    ROLLBACK TRANSACTION;
    PRINT N'فقط نمایش بود؛ هیچ تغییری نماند. برای اجرای واقعی @apply = 1.';
END
