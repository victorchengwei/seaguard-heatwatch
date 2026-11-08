"""Daily check-in, message tone, re-engagement and heat-adaptation plan.

Workers are people: mood and energy go up and down. HeatWatch respects that.

Rules (fixed, tested):
  1. The check-in is voluntary. Skipping it changes nothing and is never
     counted against the worker.
  2. Mood is private to the worker. The supervisor never sees it; the health
     office sees only an anonymous check-in RATE with small-cell suppression.
  3. A check-in can only make limits STRICTER (more care on a hard day). It can
     never loosen a limit, and it can never change a RED.
  4. Tone: the worker chooses "gentle" or "direct" words for GREEN and AMBER.
     RED is always firm, short and clear, and cannot be changed or muted.
     Firm means clear, never rude or blaming.
  5. No blame. A missed day or a lapse never resets progress to zero.
  6. Never used for discipline, performance rating, hiring, or by employers,
     insurers or others to penalise a worker. It is not a mental-health test.
"""
from __future__ import annotations

from heatwatch.privacy import MIN_CELL

MOODS = {
    "good":     {"icon": "😀", "en": "Good",            "ar": "جيد",            "caution": False},
    "ok":       {"icon": "🙂", "en": "OK",              "ar": "بخير",           "caution": False},
    "tired":    {"icon": "😩", "en": "Tired",           "ar": "متعب",           "caution": True},
    "stressed": {"icon": "😟", "en": "Stressed / down", "ar": "متوتر / محبط",   "caution": True},
}
# Fasting (e.g. Ramadan) raises dehydration risk: treated like a hard day.
FASTING = {"en": "Fasting today", "ar": "صائم اليوم"}
SLEEP = {"good": {"en": "Slept well", "ar": "نمت جيداً", "caution": False},
         "poor": {"en": "Slept badly", "ar": "نمت بشكل سيئ", "caution": True}}
TONES = ("gentle", "direct")

# Messages by level and tone. RED has one firm text only (locked).
MESSAGES = {
    "GREEN": {
        "gentle": {"en": "You're doing well. Keep sipping water, about a cup every 15-20 minutes.",
                   "ar": "أنت تقوم بعمل جيد. استمر في شرب الماء، كوب تقريباً كل 15 إلى 20 دقيقة."},
        "direct": {"en": "All good. Drink one cup of water every 15-20 minutes.",
                   "ar": "كل شيء جيد. اشرب كوب ماء كل 15 إلى 20 دقيقة."}},
    "AMBER": {
        "gentle": {"en": "You're working hard in real heat. Let's take 15 minutes in the shade with some water. Your body will thank you.",
                   "ar": "أنت تعمل بجد في حرارة حقيقية. لنأخذ 15 دقيقة في الظل مع بعض الماء. جسمك سيشكرك."},
        "direct": {"en": "Break now: 15 minutes in the shade. Drink water.",
                   "ar": "استراحة الآن: 15 دقيقة في الظل. اشرب الماء."}},
    "RED": {
        "firm": {"en": "STOP WORK NOW. Go to the cool area. Your supervisor is coming.",
                 "ar": "توقف عن العمل الآن. اذهب إلى المكان البارد. المشرف قادم إليك."}},
    "DATA GAP": {
        "gentle": {"en": "We can't see your band right now. Please check it is on your wrist; your supervisor will come by.",
                   "ar": "لا نستطيع رؤية سوارك الآن. تأكد من أنه على معصمك؛ سيمر عليك المشرف."},
        "direct": {"en": "Band signal lost. Refit the band. Supervisor will check on you.",
                   "ar": "فقدت إشارة السوار. أعد تثبيت السوار. سيتفقدك المشرف."}},
}

CHECKIN_REPLY = {
    False: {"en": "Thanks for checking in. Have a safe shift.",
            "ar": "شكراً على المشاركة. نتمنى لك مناوبة آمنة."},
    True: {"en": "Thanks for telling us. Hard days happen to everyone. Today your limits are a little stricter, so you get a break sooner. Nobody else sees your answer.",
           "ar": "شكراً لإخبارنا. الأيام الصعبة تحدث للجميع. اليوم حدودك أكثر صرامة قليلاً، لتحصل على استراحة أسرع. لا أحد غيرك يرى إجابتك."},
}

SUPPORT = {"en": "Feeling down for several days? You can talk to someone in confidence (employee support line or site medic). This is your choice; nobody is told.",
           "ar": "تشعر بالإحباط منذ عدة أيام؟ يمكنك التحدث مع شخص بسرية (خط دعم الموظفين أو المسعف). هذا اختيارك؛ لن يتم إبلاغ أحد."}

NOT_USED_FOR = ["discipline or performance rating", "hiring or contract decisions",
                "insurance pricing or claims", "sharing mood with the supervisor or employer"]


def checkin(mood: str | None, sleep: str | None = None, lang: str = "en", fasting: bool = False) -> dict:
    """Result of a daily check-in. None/skip = no change, no penalty."""
    lang = lang if lang in ("en", "ar") else "en"
    if mood is None and sleep is None and not fasting:
        return {"extra_caution": False, "reply": "", "private": True, "skipped": True}
    caution = bool((mood in MOODS and MOODS[mood]["caution"]) or (sleep in SLEEP and SLEEP[sleep]["caution"])
                   or fasting)
    return {"extra_caution": caution, "reply": CHECKIN_REPLY[caution][lang], "private": True, "skipped": False}


# Workers' home languages common on Gulf sites. DRAFT translations of the
# short safety texts only: each must be checked by a native speaker before use.
WORKER_LANGS = {
    "hi": {"name": "हिन्दी", "rtl": False,
           "GREEN": ("सामान्य", "काम जारी रखें। हर 15-20 मिनट में पानी पिएँ।"),
           "AMBER": ("सावधान", "अभी आराम करें: 15 मिनट छाँव में। पानी पिएँ।"),
           "RED": ("काम रोकें", "अभी काम रोकें। ठंडी जगह पर जाएँ। आपके सुपरवाइज़र आ रहे हैं।"),
           "DATA GAP": ("डेटा नहीं", "बैंड का सिग्नल नहीं है। बैंड ठीक से पहनें। सुपरवाइज़र आपको देखने आएँगे।"),
           "paid": "गर्मी में लिया गया आराम सवेतन है। इससे आपकी तनख्वाह नहीं कटेगी।"},
    "ur": {"name": "اردو", "rtl": True,
           "GREEN": ("معمول", "کام جاری رکھیں۔ ہر 15-20 منٹ بعد پانی پئیں۔"),
           "AMBER": ("احتیاط", "ابھی وقفہ کریں: 15 منٹ سائے میں۔ پانی پئیں۔"),
           "RED": ("کام روکیں", "ابھی کام روک دیں۔ ٹھنڈی جگہ پر جائیں۔ آپ کے سپروائزر آ رہے ہیں۔"),
           "DATA GAP": ("ڈیٹا نہیں", "بینڈ کا سگنل نہیں ہے۔ بینڈ ٹھیک سے پہنیں۔ سپروائزر آپ کو دیکھنے آئیں گے۔"),
           "paid": "گرمی کا وقفہ تنخواہ کے ساتھ ہے۔ اس سے آپ کی تنخواہ نہیں کٹے گی۔"},
    "bn": {"name": "বাংলা", "rtl": False,
           "GREEN": ("স্বাভাবিক", "কাজ চালিয়ে যান। প্রতি ১৫-২০ মিনিটে পানি পান করুন।"),
           "AMBER": ("সতর্কতা", "এখনই বিরতি নিন: ১৫ মিনিট ছায়ায়। পানি পান করুন।"),
           "RED": ("কাজ বন্ধ করুন", "এখনই কাজ বন্ধ করুন। ঠান্ডা জায়গায় যান। আপনার সুপারভাইজার আসছেন।"),
           "DATA GAP": ("ডেটা নেই", "ব্যান্ডের সিগন্যাল নেই। ব্যান্ডটি ঠিকভাবে পরুন। সুপারভাইজার আপনাকে দেখতে আসবেন।"),
           "paid": "গরমের বিরতি বেতনসহ। এতে আপনার বেতন কাটা হবে না।"},
    "ne": {"name": "नेपाली", "rtl": False,
           "GREEN": ("सामान्य", "काम जारी राख्नुहोस्। हरेक १५-२० मिनेटमा पानी पिउनुहोस्।"),
           "AMBER": ("सावधान", "अहिले आराम गर्नुहोस्: १५ मिनेट छायाँमा। पानी पिउनुहोस्।"),
           "RED": ("काम रोक्नुहोस्", "अहिले नै काम रोक्नुहोस्। चिसो ठाउँमा जानुहोस्। तपाईंको सुपरभाइजर आउँदै हुनुहुन्छ।"),
           "DATA GAP": ("डाटा छैन", "ब्यान्डको सिग्नल छैन। ब्यान्ड राम्रोसँग लगाउनुहोस्। सुपरभाइजरले तपाईंलाई हेर्न आउनुहुनेछ।"),
           "paid": "गर्मीको आराम तलबसहित हो। यसले तपाईंको तलब काटिँदैन।"},
    "tl": {"name": "Tagalog", "rtl": False,
           "GREEN": ("Normal", "Ituloy ang trabaho. Uminom ng tubig tuwing 15-20 minuto."),
           "AMBER": ("Mag-ingat", "Magpahinga ngayon: 15 minuto sa lilim. Uminom ng tubig."),
           "RED": ("Itigil ang trabaho", "ITIGIL ANG TRABAHO NGAYON. Pumunta sa malamig na lugar. Papunta na ang iyong supervisor."),
           "DATA GAP": ("Walang data", "Walang signal ang band. Isuot nang maayos ang band. Pupuntahan ka ng supervisor."),
           "paid": "May bayad ang heat break. Hindi ito makakaapekto sa iyong sahod."},
    # Same short texts as the worker app (static/i18n.js), so both screens match.
    "ml": {"name": "മലയാളം", "rtl": False,
           "GREEN": ("സാധാരണ", "പതിവായി വെള്ളം കുടിക്കുക."),
           "AMBER": ("ജാഗ്രത", "ഇപ്പോൾ തണലിൽ വിശ്രമിക്കുക, വെള്ളം കുടിക്കുക, സൂപ്പർവൈസറെ അറിയിക്കുക."),
           "RED": ("ജോലി നിർത്തുക", "ജോലി നിർത്തുക, തണലിൽ ശരീരം തണുപ്പിക്കുക, മെഡിക്കിനെയോ സൂപ്പർവൈസറെയോ വിളിക്കുക."),
           "DATA GAP": ("ഡാറ്റ ഇല്ല", "ബാൻഡിന് സിഗ്നൽ ഇല്ല. ബാൻഡ് ശരിയായി ധരിക്കുക. സൂപ്പർവൈസർ നിങ്ങളെ കാണാൻ വരും."),
           "paid": "ചൂട് കാരണമുള്ള വിശ്രമത്തിന് ശമ്പളമുണ്ട്. ഇത് നിങ്ങളുടെ ശമ്പളം കുറയ്ക്കില്ല."},
    "ta": {"name": "தமிழ்", "rtl": False,
           "GREEN": ("சாதாரணம்", "தொடர்ந்து தண்ணீர் குடியுங்கள்."),
           "AMBER": ("எச்சரிக்கை", "இப்போதே நிழலில் ஓய்வெடுங்கள், தண்ணீர் குடியுங்கள், மேற்பார்வையாளரிடம் சொல்லுங்கள்."),
           "RED": ("வேலையை நிறுத்து", "வேலையை நிறுத்துங்கள், நிழலில் உடலைக் குளிர்வியுங்கள், மருத்துவ உதவியாளர் அல்லது மேற்பார்வையாளரை அழையுங்கள்."),
           "DATA GAP": ("தரவு இல்லை", "பட்டையில் சிக்னல் இல்லை. பட்டையைச் சரியாக அணியுங்கள். மேற்பார்வையாளர் உங்களைப் பார்க்க வருவார்."),
           "paid": "வெப்ப ஓய்வுக்குச் சம்பளம் உண்டு. இதனால் உங்கள் சம்பளம் குறையாது."},
    "si": {"name": "සිංහල", "rtl": False,
           "GREEN": ("සාමාන්‍ය", "නිතිපතා වතුර බොන්න."),
           "AMBER": ("අවධානය", "දැන්ම සෙවණේ විවේක ගන්න, වතුර බොන්න, අධීක්ෂකවරයාට කියන්න."),
           "RED": ("වැඩ නවත්වන්න", "වැඩ නවත්වන්න, සෙවණේ ශරීරය සිසිල් කරන්න, වෛද්‍ය සහායකයා හෝ අධීක්ෂකවරයා අමතන්න."),
           "DATA GAP": ("දත්ත නැත", "පටියේ සංඥාවක් නැත. පටිය නිවැරදිව පළඳින්න. අධීක්ෂකවරයා ඔබව බලන්න එයි."),
           "paid": "උණුසුම් විවේකයට වැටුප් ලැබේ. එයින් ඔබේ වැටුප අඩු නොවේ."},
    "sw": {"name": "Kiswahili", "rtl": False,
           "GREEN": ("Kawaida", "Kunywa maji mara kwa mara."),
           "AMBER": ("Tahadhari", "Pumzika kivulini sasa, kunywa maji, mwambie msimamizi wako."),
           "RED": ("Simamisha kazi", "Simamisha kazi, jipoze kivulini, mpigie mhudumu wa afya au msimamizi."),
           "DATA GAP": ("Hakuna data", "Bangili haina mawimbi. Vaa bangili vizuri. Msimamizi atakuja kukuangalia."),
           "paid": "Mapumziko ya joto yanalipwa. Hayapunguzi mshahara wako."},
    "zh": {"name": "中文", "rtl": False,
           "GREEN": ("正常", "定时喝水。"),
           "AMBER": ("注意", "现在到阴凉处休息，喝水，告诉你的主管。"),
           "RED": ("停止工作", "停止工作，在阴凉处降温，呼叫医护人员或主管。"),
           "DATA GAP": ("无数据", "手环没有信号。请戴好手环。主管会过来查看你。"),
           "paid": "高温休息照常计薪，不会扣你的工资。"},
}
PAID_BREAK = {"en": "Heat breaks are paid. They never cost you wages.",
              "ar": "استراحات الحر مدفوعة الأجر. لا تخصم من راتبك أبداً."}
# Pictograms so the alert is understood without reading.
PICTO = {"GREEN": "✅💧", "AMBER": "⛱️💧", "RED": "🛑❄️", "DATA GAP": "📶❓"}
ALL_LANGS = ["en", "ar"] + list(WORKER_LANGS)


def message(level: str, tone: str = "gentle", lang: str = "en", paid_breaks: bool = True) -> dict:
    """Worker message. RED is always firm and locked; tone applies to other levels.

    paid_breaks: site policy setting. When on, AMBER/RED messages say plainly
    that the break never costs wages (fear of lost pay makes workers hide symptoms).
    """
    if lang in WORKER_LANGS:
        L = WORKER_LANGS[lang]
        out = {"text": L[level][1], "level_name": L[level][0], "tone": "firm" if level == "RED" else "direct",
               "locked": level == "RED", "picto": PICTO[level], "rtl": L["rtl"],
               "draft_translation": True}
        out["paid"] = L["paid"] if (paid_breaks and level in ("AMBER", "RED")) else ""
        return out
    out = _message_en_ar(level, tone, lang if lang in ("en", "ar") else "en")
    out.update(picto=PICTO[level], rtl=(lang == "ar"), draft_translation=False,
               paid=PAID_BREAK[lang if lang in ("en", "ar") else "en"]
               if (paid_breaks and level in ("AMBER", "RED")) else "")
    return out


def _message_en_ar(level: str, tone: str, lang: str) -> dict:
    if level == "RED":
        return {"text": MESSAGES["RED"]["firm"][lang], "tone": "firm", "locked": True}
    tone = tone if tone in TONES else "gentle"
    return {"text": MESSAGES[level][tone][lang], "tone": tone, "locked": False}


def reengage(days_since_last: int, total_checkins: int, lang: str = "en") -> str:
    """Friendly, blame-free nudge after missed days. Progress is never reset."""
    if days_since_last <= 1:
        return ""
    if lang == "ar":
        return (f"مرحباً بعودتك! ما زالت مشاركاتك الـ {total_checkins} محسوبة. "
                "شارك متى شئت، بنقرة واحدة.")
    return (f"Welcome back! Your {total_checkins} check-ins still count. "
            "Check in whenever you like; it takes one tap.")


def low_mood_streak(history: list) -> bool:
    """True if the last 3 check-ins were 'stressed'. Shows SUPPORT to the worker only."""
    return len(history) >= 3 and all(m == "stressed" for m in history[-3:])


def acclimatisation_plan(days_in_heat: int) -> list:
    """7-day heat-adaptation plan for new or returning workers.

    NIOSH (2016) Criteria for a Recommended Standard: Occupational Exposure to
    Heat and Hot Environments: new workers no more than 20 % of the usual
    duration of heat exposure on day 1, increasing by no more than 20 % each
    additional day. To be confirmed by the site medic / clinical mentors.
    """
    plan = []
    for d in range(1, 8):
        share = min(100, 20 * d)
        plan.append({"day": d, "max_heat_exposure_pct": share,
                     "done": d <= days_in_heat,
                     "tip": "Extra breaks and water; tell your supervisor if you feel unwell."})
    return plan


def checkin_rate(n_checked: int, n_workers: int, min_cell: int = MIN_CELL) -> dict:
    """Anonymous check-in rate for the health office. Never individual moods."""
    if n_workers < min_cell:
        return {"workers": f"<{min_cell}", "rate": "suppressed (group too small)"}
    return {"workers": n_workers, "rate": round(n_checked / n_workers, 2)}
