// i18n Translations
const TRANSLATIONS = {
  en: {
    appTitle: "Platinum Experience",
    guide: "Guide",
    myTrips: "✈️ My Trips",
    refine: "Refine",
    allFiltersOff: "All filters off",
    search: "Search",
    sort: "Sort",
    favorites: "❤️ Favorites only",
    currency: "Currency",
    map: "Map",
    browseMap: "Browse on the map, then use the detail panel for the exact source link",
    fullTable: "Full table",
    sideBySide: "Side-by-side comparison",
    clearFilters: "Clear filters",
    exportCsv: "↓ CSV",
    share: "🔗 Share",
    nameAz: "Name (A-Z)",
    nameZa: "Name (Z-A)",
    ratingHigh: "Rating (High to Low)",
    ratingLow: "Rating (Low to High)",
    country: "Country",
    city: "City",
    cuisine: "Cuisine",
    googleRating: "Google rating",
    minReviews: "Min reviews",
    tabelogRating: "Tabelog rating",
    lunchBand: "Lunch band",
    dinnerBand: "Dinner band",
    children: "Children",
    englishMenu: "English menu",
    reservation: "Reservation",
  },
  ja: {
    appTitle: "プラチナムエクスペリエンス",
    guide: "ガイド",
    myTrips: "✈️ 私の旅行",
    refine: "絞り込む",
    allFiltersOff: "フィルターなし",
    search: "検索",
    sort: "並び替え",
    favorites: "❤️ お気に入りのみ",
    currency: "通貨",
    map: "地図",
    browseMap: "地図を参照してから、詳細パネルで正確なソースリンクを確認してください",
    fullTable: "完全なテーブル",
    sideBySide: "並べて比較",
    clearFilters: "フィルターをクリア",
    exportCsv: "↓ CSV",
    share: "🔗 共有",
    nameAz: "名前 (A-Z)",
    nameZa: "名前 (Z-A)",
    ratingHigh: "評価 (高から低)",
    ratingLow: "評価 (低から高)",
    country: "国",
    city: "都市",
    cuisine: "料理",
    googleRating: "Google評価",
    minReviews: "最小レビュー",
    tabelogRating: "Tabelog評価",
    lunchBand: "ランチ帯",
    dinnerBand: "ディナー帯",
    children: "お子さん",
    englishMenu: "英語メニュー",
    reservation: "予約",
  },
  zh: {
    appTitle: "铂金体验",
    guide: "指南",
    myTrips: "✈️ 我的旅行",
    refine: "筛选",
    allFiltersOff: "无筛选",
    search: "搜索",
    sort: "排序",
    favorites: "❤️ 仅收藏夹",
    currency: "货币",
    map: "地图",
    browseMap: "浏览地图，然后使用详细信息面板获取确切的源链接",
    fullTable: "完整表",
    sideBySide: "并排比较",
    clearFilters: "清除筛选器",
    exportCsv: "↓ CSV",
    share: "🔗 分享",
    nameAz: "名称 (A-Z)",
    nameZa: "名称 (Z-A)",
    ratingHigh: "评分 (高到低)",
    ratingLow: "评分 (低到高)",
    country: "国家",
    city: "城市",
    cuisine: "菜系",
    googleRating: "谷歌评分",
    minReviews: "最少评论",
    tabelogRating: "Tabelog评分",
    lunchBand: "午餐价格",
    dinnerBand: "晚餐价格",
    children: "儿童",
    englishMenu: "英文菜单",
    reservation: "预订",
  }
};

let currentLanguage = localStorage.getItem("amex-language") || "en";

function setLanguage(lang) {
  currentLanguage = lang;
  localStorage.setItem("amex-language", lang);
}

function t(key) {
  return TRANSLATIONS[currentLanguage]?.[key] || TRANSLATIONS["en"]?.[key] || key;
}

function updatePageLanguage() {
  // Update common UI elements with translations
  const elements = document.querySelectorAll("[data-i18n]");
  elements.forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (el.tagName === "INPUT" || el.tagName === "SELECT") {
      el.placeholder = t(key);
    } else {
      el.textContent = t(key);
    }
  });
}
