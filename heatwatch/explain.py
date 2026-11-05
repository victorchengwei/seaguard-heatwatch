"""Plain-language explanations, actions and escalation (English / Arabic).

Rules decide, AI only explains, people decide.

The level and the action ALWAYS come from the rules engine. This module only
turns the rules' reasons into short, plain words for workers and supervisors.

Explainer modes:
  * "template" (default): fixed, reviewed sentences. Works offline.
  * "ai": an LLM rewrites the template text (key read from the environment
    variable HEATWATCH_AI_KEY at deploy time). Not enabled in the prototype.
If the explainer fails, the failure is shown openly and the alert, level and
action stand unchanged. An explanation can never change a level.
"""
from __future__ import annotations

import os

LANGS = ("en", "ar")

ACTION = {
    "GREEN": {"en": "Keep working. Drink water every 15-20 minutes.",
              "ar": "واصل العمل. اشرب الماء كل 15 إلى 20 دقيقة."},
    "AMBER": {"en": "Take a 15-minute break in the shade and drink water. Your supervisor will check on you.",
              "ar": "خذ استراحة لمدة 15 دقيقة في الظل واشرب الماء. سيتفقدك المشرف."},
    "RED": {"en": "Stop work now. Move to a cool place. Your supervisor is coming to you.",
            "ar": "توقف عن العمل الآن. انتقل إلى مكان بارد. المشرف قادم إليك."},
    "DATA GAP": {"en": "No reliable signal. Your supervisor will check on you in person.",
                 "ar": "لا توجد إشارة موثوقة. سيتفقدك المشرف شخصياً."},
}

LEVEL_NAME = {
    "GREEN": {"en": "Normal", "ar": "طبيعي"},
    "AMBER": {"en": "Caution", "ar": "تنبيه"},
    "RED": {"en": "Stop work", "ar": "أوقف العمل"},
    "DATA GAP": {"en": "No data", "ar": "لا توجد بيانات"},
}

MEANS = {
    "GREEN": {"means": {"en": "Body and environment signals are inside the screening limits right now.",
                        "ar": "إشارات الجسم والبيئة ضمن الحدود الآن."},
              "not": {"en": "It is not a medical clearance. If you feel unwell, press 'I feel unwell'.",
                      "ar": "هذا ليس تصريحاً طبياً. إذا شعرت بتوعك، اضغط على زر 'أشعر بتوعك'."}},
    "AMBER": {"means": {"en": "Heat strain is building. A break now prevents a stop later.",
                        "ar": "الإجهاد الحراري يتزايد. الاستراحة الآن تمنع التوقف لاحقاً."},
              "not": {"en": "It is not a diagnosis of illness.",
                      "ar": "هذا ليس تشخيصاً لمرض."}},
    "RED": {"means": {"en": "High risk of heat illness. Act now.",
                      "ar": "خطر مرتفع للإصابة بمرض حراري. تصرف الآن."},
            "not": {"en": "It is not a diagnosis. The supervisor and the site medic decide what happens next.",
                    "ar": "هذا ليس تشخيصاً. المشرف والمسعف في الموقع يقرران الخطوة التالية."}},
    "DATA GAP": {"means": {"en": "The system cannot see this worker's signals.",
                           "ar": "لا يستطيع النظام رؤية إشارات هذا العامل."},
                 "not": {"en": "It does not mean the worker is safe.",
                         "ar": "هذا لا يعني أن العامل بأمان."}},
}

# Supervisor escalation ladder. Minutes from the alert.
LADDER = {
    "RED": [
        (0, {"en": "Band vibrates; worker sees 'Stop work'.", "ar": "يهتز السوار؛ يرى العامل 'أوقف العمل'."}),
        (0, {"en": "Supervisor alerted with location.", "ar": "يتم تنبيه المشرف مع الموقع."}),
        (2, {"en": "Not acknowledged: site medic / safety officer alerted.",
             "ar": "لم يتم التأكيد: يتم تنبيه المسعف أو مسؤول السلامة."}),
        (5, {"en": "Still not resolved: emergency call as in the site plan.",
             "ar": "لم تُحل المشكلة: اتصال طوارئ حسب خطة الموقع."}),
    ],
    "AMBER": [
        (0, {"en": "Worker told to take a 15-minute shaded break.", "ar": "يُطلب من العامل استراحة 15 دقيقة في الظل."}),
        (0, {"en": "Supervisor notified.", "ar": "يتم إبلاغ المشرف."}),
        (15, {"en": "Re-check after the break. Still AMBER: treat as RED.",
              "ar": "إعادة الفحص بعد الاستراحة. إذا بقي تنبيه: يعامل كخطر."}),
    ],
    "DATA GAP": [
        (0, {"en": "Supervisor told the signal is missing.", "ar": "يتم إبلاغ المشرف بأن الإشارة مفقودة."}),
        (5, {"en": "Supervisor checks the worker in person.", "ar": "يتفقد المشرف العامل شخصياً."}),
    ],
    "GREEN": [],
}

# Reason keywords -> plain words without health numbers (supervisor-safe).
_PLAIN = [
    ("Estimated core", {"en": "Body heat estimate is high.", "ar": "تقدير حرارة الجسم مرتفع."}),
    ("WBGT in danger zone", {"en": "Very hot conditions and a high heart rate together.",
                             "ar": "ظروف حارة جداً مع معدل نبض مرتفع."}),
    ("Sustained HR", {"en": "Heart rate has stayed high.", "ar": "بقي معدل النبض مرتفعاً."}),
    ("not acclimatised", {"en": "Heavy work in heat, not yet used to the heat.",
                          "ar": "عمل شاق في الحر، ولم يتأقلم بعد."}),
    ("Slow heart-rate recovery", {"en": "Heart rate is slow to recover after rest.",
                                  "ar": "معدل النبض بطيء في التعافي بعد الراحة."}),
    ("HR missing", {"en": "No heart-rate signal: level based on site heat only.",
                    "ar": "لا توجد إشارة نبض: المستوى مبني على حرارة الموقع فقط."}),
    ("No body or environment", {"en": "No signal at all: check the worker in person.",
                                "ar": "لا توجد أي إشارة: تفقد العامل شخصياً."}),
    ("All body and environment", {"en": "Signals inside limits.", "ar": "الإشارات ضمن الحدود."}),
]

_FLAG_PLAIN = [
    ("off wrist", {"en": "Band may be off the wrist (reading 0 treated as missing, never as zero).",
                   "ar": "قد يكون السوار خارج المعصم (القراءة صفر تعامل كمفقودة)."}),
    ("no wearable consent", {"en": "Worker declined the band: environment-only level.",
                             "ar": "رفض العامل السوار: المستوى مبني على البيئة فقط."}),
    ("artefact", {"en": "Short movement spike ignored.", "ar": "تم تجاهل قفزة قصيرة بسبب الحركة."}),
    ("network", {"en": "No network: band alerts on its own; data sent later.",
                 "ar": "لا توجد شبكة: السوار ينبه بنفسه؛ ترسل البيانات لاحقاً."}),
    ("battery", {"en": "Band battery low.", "ar": "بطارية السوار منخفضة."}),
    ("impossible", {"en": "Site heat sensor reading rejected; weather feed used.",
                    "ar": "تم رفض قراءة مستشعر الحرارة؛ استخدمت بيانات الطقس."}),
    ("daily check-in", {"en": "Your own check-in asked for extra care today: an earlier break.",
                        "ar": "طلبت مشاركتك اليومية عناية إضافية اليوم: استراحة أبكر."}),
    ("age missing", {"en": "Profile incomplete: stricter default limit used.",
                     "ar": "الملف غير مكتمل: استخدم حد أكثر صرامة."}),
]


def plain_reasons(reasons, flags, lang="en"):
    """Turn rule reasons and guardrail flags into plain, number-free lines."""
    out = []
    for r in reasons:
        for key, txt in _PLAIN:
            if key in r:
                out.append(txt[lang])
                break
    for f in flags:
        for key, txt in _FLAG_PLAIN:
            if key in f and txt[lang] not in out:
                out.append(txt[lang])
                break
    if any("PPE" in r or "suit" in r for r in reasons):
        out.append({"en": "Protective suit traps heat.", "ar": "البدلة الواقية تحبس الحرارة."}[lang])
    return out


def explain(level, reasons, flags, lang="en", mode=None, fail=False):
    """Explanation for one result. Never changes the level or the action.

    fail=True simulates an explainer outage, to show the visible-failure path.
    """
    lang = lang if lang in LANGS else "en"
    mode = mode or os.environ.get("HEATWATCH_EXPLAINER", "template")
    base = {"level": level, "level_name": LEVEL_NAME[level][lang], "action": ACTION[level][lang],
            "means": MEANS[level]["means"][lang], "does_not_mean": MEANS[level]["not"][lang],
            "ladder": [{"min": m, "step": s[lang]} for m, s in LADDER[level]]}
    if fail or (mode == "ai" and not os.environ.get("HEATWATCH_AI_KEY")):
        base.update(status="failed", source="none", why=[],
                    notice={"en": "Explanation service unavailable. The alert and the action above still stand: rules decide.",
                            "ar": "خدمة الشرح غير متاحة. التنبيه والإجراء أعلاه ما زالا قائمين: القواعد تقرر."}[lang])
        return base
    base.update(status="ok", source="template", why=plain_reasons(reasons, flags, lang), notice="")
    return base
