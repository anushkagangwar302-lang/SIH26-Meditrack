import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Lang = "en" | "hi";

const dict = {
  en: {
    brand: "Anustan",
    tagline: "AI Patient Intake",
    signInKicker: "Secure access",
    signInTitle: "Sign in to continue intake",
    signInSub: "Your clinical conversations stay private and encrypted.",
    email: "Email",
    methodEmail: "Email",
    methodAbha: "ABHA ID",
    methodAadhaar: "Aadhaar",
    abhaLabel: "ABHA number or ABHA address",
    abhaHelp: "14-digit ABHA number, or an address like name@abdm",
    aadhaarLabel: "Aadhaar number",
    aadhaarHelp: "12-digit number, used only to identify your record",
    idInvalidAbha: "Enter a valid 14-digit ABHA number or ABHA address.",
    idInvalidAadhaar: "Enter a valid 12-digit Aadhaar number.",
    govNote: "Official ABHA and Aadhaar verification needs approval from the national health authority; until then this creates a regular secure account linked to your ID.",
    password: "Password",
    signIn: "Sign in",
    signUp: "Create account",
    google: "Continue with Google",
    noAccount: "New here? Create an account",
    haveAccount: "Already registered? Sign in",
    working: "Please wait…",
    checkEmail: "Check your email to confirm your account.",
    signedIn: "Signed in.",
    signOut: "Sign out",
    emergency: "Emergency red flags",
    emergencyKicker: "Urgent triage",
    emergencyTitle: "Red flag symptoms",
    emergencySub: "If any of these are present, seek care immediately — do not wait for the intake to finish.",
    callNow: "Call emergency services",
    escalate: "Alert consulting physician",
    escalated: "Physician alerted for immediate review.",
    back: "Back to sign in",
    disclaimer: "Guidance only — reviewed by AI, not diagnostic.",
    flags: [
      { t: "Chest pain or pressure", d: "Crushing pain, spreading to arm or jaw, with sweating" },
      { t: "Breathlessness at rest", d: "Struggling to speak full sentences, blue lips" },
      { t: "Very high fever", d: "Above 103°F with confusion, stiff neck or rash" },
      { t: "Ongoing bleeding", d: "Bleeding that does not stop, vomiting blood, black stools" },
      { t: "Sudden weakness or slurred speech", d: "Face droop, one-sided weakness, sudden vision loss" },
      { t: "Fainting or seizure", d: "Loss of consciousness, fits, unresponsive person" },
      { t: "Severe dehydration", d: "No urine for 12 hours, sunken eyes, drowsiness" },
      { t: "Pregnancy warning signs", d: "Bleeding, severe abdominal pain, reduced baby movement" },
    ],
  },
  hi: {
    brand: "अनुस्तान",
    tagline: "एआई रोगी पंजीकरण",
    signInKicker: "सुरक्षित प्रवेश",
    signInTitle: "जारी रखने के लिए साइन इन करें",
    signInSub: "आपकी चिकित्सकीय बातचीत निजी और सुरक्षित रहती है।",
    email: "ईमेल",
    methodEmail: "ईमेल",
    methodAbha: "आभा आईडी",
    methodAadhaar: "आधार",
    abhaLabel: "आभा नंबर या आभा पता",
    abhaHelp: "14 अंकों का आभा नंबर, या name@abdm जैसा पता",
    aadhaarLabel: "आधार नंबर",
    aadhaarHelp: "12 अंकों का नंबर, केवल आपका रिकॉर्ड पहचानने के लिए",
    idInvalidAbha: "मान्य 14 अंकों का आभा नंबर या आभा पता दर्ज करें।",
    idInvalidAadhaar: "मान्य 12 अंकों का आधार नंबर दर्ज करें।",
    govNote: "आधिकारिक आभा और आधार सत्यापन के लिए राष्ट्रीय स्वास्थ्य प्राधिकरण की अनुमति आवश्यक है; तब तक आपकी आईडी से जुड़ा एक सुरक्षित खाता बनाया जाता है।",
    password: "पासवर्ड",
    signIn: "साइन इन करें",
    signUp: "खाता बनाएँ",
    google: "Google से जारी रखें",
    noAccount: "नए हैं? खाता बनाएँ",
    haveAccount: "पहले से पंजीकृत हैं? साइन इन करें",
    working: "कृपया प्रतीक्षा करें…",
    checkEmail: "खाता पुष्टि के लिए अपना ईमेल देखें।",
    signedIn: "साइन इन हो गया।",
    signOut: "साइन आउट",
    emergency: "आपातकालीन चेतावनी",
    emergencyKicker: "तत्काल ट्राइएज",
    emergencyTitle: "गंभीर चेतावनी लक्षण",
    emergencySub: "इनमें से कोई भी लक्षण हो तो तुरंत इलाज लें — पंजीकरण पूरा होने का इंतज़ार न करें।",
    callNow: "आपातकालीन सेवा को कॉल करें",
    escalate: "परामर्शी चिकित्सक को सूचित करें",
    escalated: "चिकित्सक को तत्काल समीक्षा हेतु सूचित कर दिया गया।",
    back: "साइन इन पर वापस",
    disclaimer: "केवल मार्गदर्शन — एआई द्वारा समीक्षित, निदान नहीं।",
    flags: [
      { t: "छाती में दर्द या दबाव", d: "तेज़ दर्द, हाथ या जबड़े तक फैलना, पसीना" },
      { t: "आराम में भी सांस फूलना", d: "पूरा वाक्य बोलने में कठिनाई, होंठ नीले पड़ना" },
      { t: "बहुत तेज़ बुखार", d: "103°F से अधिक, साथ में भ्रम, गर्दन में अकड़न या दाने" },
      { t: "लगातार रक्तस्राव", d: "रक्तस्राव न रुकना, खून की उल्टी, काला मल" },
      { t: "अचानक कमजोरी या लड़खड़ाती बोली", d: "चेहरा टेढ़ा, एक तरफ कमजोरी, अचानक दृष्टि जाना" },
      { t: "बेहोशी या दौरा", d: "होश खोना, झटके आना, प्रतिक्रिया न देना" },
      { t: "गंभीर निर्जलीकरण", d: "12 घंटे से पेशाब नहीं, आँखें धँसी, अत्यधिक नींद" },
      { t: "गर्भावस्था में चेतावनी", d: "रक्तस्राव, तेज़ पेट दर्द, शिशु की हलचल कम होना" },
    ],
  },
} as const;

type Dict = typeof dict.en;

const I18nContext = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: Dict }>({
  lang: "en",
  setLang: () => {},
  t: dict.en,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>("en");

  useEffect(() => {
    const saved = localStorage.getItem("anustan-lang");
    if (saved === "hi" || saved === "en") setLang(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem("anustan-lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t: dict[lang] as Dict }}>
      {children}
    </I18nContext.Provider>
  );
}

export const useI18n = () => useContext(I18nContext);

export function LanguageToggle() {
  const { lang, setLang } = useI18n();
  return (
    <div className="flex items-center gap-2">
      {(["en", "hi"] as Lang[]).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          className={`rounded-full px-4 py-2 text-sm font-semibold transition-colors ${
            lang === l
              ? "bg-card text-foreground shadow-soft"
              : "bg-card/50 text-muted-foreground hover:bg-card/80"
          }`}
        >
          {l === "en" ? "English" : "हिन्दी"}
        </button>
      ))}
    </div>
  );
}
