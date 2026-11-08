import { useLanguage } from './i18n.js'

export default function LanguageSelect() {
  const [language, setLanguage] = useLanguage()
  return <select className="language-switch" aria-label="Interface language" value={language}
    onChange={(e) => setLanguage(e.target.value)}>
    <option value="en">English</option><option value="zh-CN">中文</option>
  </select>
}
