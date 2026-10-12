"""話術分類體系：說服手法、詐騙階段、詐騙類型（SPEC §8）。

seed.py 用它建立查找表，analyzer.py 用它寫提示詞與驗證輸出，樣板用它顯示中文名稱。
"""

# (code, 中文, 英文原名, 定義與典型說法, 顏色)
TACTICS = [
    ("reciprocity", "互惠", "Reciprocation",
     "先給好處再要求回報：先送小禮、先讓你小賺一筆、「我幫了你，你也幫我一下」", "#9a6a22"),
    ("commitment", "承諾一致", "Commitment and Consistency",
     "先要求小承諾再逐步加碼：「你上次都說好了」「都已經投了，不差這一筆」", "#6a5a8c"),
    ("social_proof", "社會認同", "Social Proof",
     "以他人行為證明可信：「群組裡大家都賺了」、截圖別人的獲利", "#3d6b76"),
    ("liking", "喜好", "Liking",
     "讓對方喜歡自己：大量讚美、裝熟、展示共同興趣、曖昧示好", "#a5506f"),
    ("authority", "權威", "Authority",
     "以身分或專業取信：自稱分析師、檢察官、銀行專員、出示證件照片", "#2e4b78"),
    ("scarcity", "稀少性", "Scarcity",
     "強調機會有限：「名額只剩今天」「錯過就沒了」「限時優惠」", "#c2492b"),
    ("unity", "團結", "Unity",
     "強調共同身分：「我們是自己人」「同鄉」「家人才跟你說」", "#5c6a2a"),
    ("urgency_threat", "威脅恐嚇", "Threat / Intimidation (non-Cialdini)",
     "以損失或法律責任恐嚇：帳戶將被凍結、涉及洗錢、不配合就通緝", "#8a2c20"),
]

# (code, 名稱, 說明)
STAGES = [
    ("contact", "接觸", "初次搭話、加好友、打錯人"),
    ("rapport", "建立關係", "閒聊、分享生活、示好"),
    ("setup", "鋪陳", "提到投資、包裹、帳戶問題等，但尚未要求行動"),
    ("action", "要求行動", "要求匯款、提供驗證碼或帳號、點連結、下載 App、加入群組"),
    ("pressure", "施壓", "催促、威脅、情緒勒索"),
    ("none", "無", "一般內容"),
]

# (code, 名稱, 說明)
SCAM_TYPES = [
    ("investment", "假投資", "假冒投資老師或分析師，誘導加入群組、下載假投資 App 入金"),
    ("romance", "感情詐騙", "以交往或曖昧關係建立信任，再以各種理由借錢或投資"),
    ("shopping", "網購解除分期／假買家", "假冒客服稱訂單設定錯誤需解除分期，或假買家要求賣家操作金流"),
    ("impersonation_family", "假冒親友", "假冒親友換新號碼，以急用為由借錢"),
    ("impersonation_official", "假冒公務員", "假冒檢警、法院或公務機關，稱涉案需監管帳戶"),
    ("job", "求職打工", "以高薪輕鬆工作為餌，要求繳費、提供帳戶或先墊款"),
    ("phishing", "釣魚連結／盜帳號", "誘騙點擊連結、輸入帳密或提供驗證碼"),
    ("other", "其他", "其他詐騙類型"),
]

TACTIC_CODES = [t[0] for t in TACTICS]
STAGE_CODES = [s[0] for s in STAGES]
SCAM_TYPE_CODES = [s[0] for s in SCAM_TYPES]

TACTIC_NAMES = {t[0]: t[1] for t in TACTICS}
TACTIC_COLORS = {t[0]: t[4] for t in TACTICS}
STAGE_NAMES = {s[0]: s[1] for s in STAGES}
SCAM_TYPE_NAMES = {s[0]: s[1] for s in SCAM_TYPES}

RISK_LEVEL_NAMES = {"low": "低", "medium": "中", "high": "高"}
