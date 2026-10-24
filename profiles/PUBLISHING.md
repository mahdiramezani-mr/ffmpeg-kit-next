# انتشار Studio

بیلد Android، iOS، macOS و Windows x64 روی GitHub Actions انجام می‌شود.
شاخه پیش‌فرض `main` می‌ماند؛ فقط ورودی اجرای workflow روی آن است.
ابزارها، تنظیمات و پچ‌ها در شاخه `profiles` نگهداری می‌شوند.

## انتشار هر نسخه

1. در [Actions → Publish Studio](https://github.com/mahdiramezani-mr/ffmpeg-kit-next/actions/workflows/publish-studio.yml) روی **Run workflow** بزن.
2. شاخه را `main` نگه دار و `upstream_tag` را وارد کن؛ مثلاً `v9.0.2`.
3. `build_number=0` را نگه دار تا شماره آزاد بعدی خودکار انتخاب شود؛ خروجی مثلاً `v9.0.2-studio.1` خواهد بود.
4. `mode=draft` را برای مرور خروجی یا `mode=publish` را برای انتشار خودکار پس از موفقیت همه بیلدها انتخاب کن.
5. **Run workflow** را بزن. چهار بیلد موازی اجرا می‌شوند؛ انتقال فایل، ساخت تگ و بارگذاری بسته‌ها خودکار است.
6. در حالت Draft، خروجی را بررسی و در **Releases** روی **Publish release** بزن؛ بیلد دوباره لازم نیست.

`draft` نیز تگ قابل مصرف را push می‌کند. `build-only` هیچ تگ یا Release ریموت ایجاد نمی‌کند و خروجی را فقط به‌صورت artifact نگه می‌دارد.
برای تبدیل اجرای build-only به Release از رابط، اجرای تازه لازم است؛ برای استفاده عادی Draft را انتخاب کن.
تگ منتشرشده هرگز جابه‌جا نمی‌شود. شماره ساخت مشخص نیز قابل واردکردن است.

## افزودن تغییر اختصاصی

1. روی شاخه `profiles` کار کن.
2. patch را در `profiles/ci/patches/` اضافه کن و مسیرش را در `profiles/publish.json` ثبت کن.
3. فلگ‌ها، معماری‌ها، LLVM و Xcode نیز از همین JSON و اسکریپت راه‌اندازی Windows تنظیم می‌شوند.
4. تغییرات را commit و فقط `profiles` را push کن؛ سپس workflow را از `main` اجرا کن.
5. اگر upstream دقیقاً همان patch را داشته باشد، اعمال مجدد آن رد می‌شود؛ conflict با نام patch بیلد را متوقف می‌کند و باید سازگاری آن بررسی شود.

به merge پچ‌های native یا باینری‌ها در `main` نیازی نیست. تگ همیشه از سورس تگ upstream به‌علاوه پچ‌های انتخاب‌شده و چهار بسته ساخته می‌شود.
فایل `.github/workflows/publish-studio.yml` روی `main` یک ورودی کوچک است که workflow شاخه `profiles` را صدا می‌زند.
نسخه مرجع این ورودی در `profiles/ci/dispatch.yml` است؛ فقط اگر خود ورودی‌ها را تغییر دادی، آن را روی `main` هم به‌روز کن.
برای افزودن patch یا تغییر فلگ، تغییری در `main` لازم نیست.

## خطا و اجرای دوباره

- برای خطای موقت **Re-run failed jobs** را بزن؛ artifactها ۱۴ روز نگه داشته می‌شوند.
- تغییر ابزار یا patch در اجرای قبلی وارد نمی‌شود؛ برای آن اجرای تازه لازم است.
- اگر push تگ موفق و ایجاد Release ناموفق شده باشد، اجرای دوباره فقط با محتوای یکسان تگ ادامه می‌دهد.
- اگر تگ موجود است، برای اجرای تازه شماره `0` را نگه دار؛ تگ قبلی بازنویسی نمی‌شود.
- سقف هر job میزبانی‌شده ۶ ساعت است. اگر بیلد از سقف عبور کند، همان پلتفرم باید بر اساس معماری تقسیم شود.
- Windows فعلاً LLVM `22.1.8` دارد؛ تغییر آن نیازمند هماهنگی نسخه بسته‌ها در `setup-windows.sh` است. Xcode فعلاً `26.6` است.

## خروجی و استفاده

- تگ شامل باینری‌های native است؛ Flutter همان مسیر `flutter/flutter` را مصرف می‌کند.
- چهار بسته `.tar.gz` و checksum هرکدام به Release پیوست می‌شوند.
- `release-build.json` سورس upstream و FFmpeg، ابزارها و patchها، فلگ‌ها و hash فایل‌ها را ثبت می‌کند.
- Windows و macOS تست native نسخه، کتابخانه‌ها، blur و cancellation دارند.
- Android/iOS از نظر بسته‌بندی، معماری و نسخه بررسی می‌شوند؛ اجرای برنامه Flutter روی دستگاه جزو CI نیست.
- پروفایل فعلی شامل Linux، Web، tvOS، visionOS و Windows arm64 نیست.
- secret یا PAT جدید لازم نیست؛ workflow از `GITHUB_TOKEN` استفاده می‌کند و فقط job انتشار دسترسی نوشتن دارد.

```yaml
dependencies:
  ffmpeg_kit_next_flutter:
    git:
      url: https://github.com/mahdiramezani-mr/ffmpeg-kit-next.git
      path: flutter/flutter
      ref: v9.0.2-studio.1
```

ثبت Maven محلی Android و تنظیمات Apple/Windows مطابق `flutter/flutter/BUILD.md` لازم است.
از `git push --tags` یا force-push استفاده نکن؛ workflow فقط تگ همان انتشار را push می‌کند.

## بررسی محلی ابزار

```powershell
python -m unittest discover -s profiles/ci -p "test_*.py"
```
