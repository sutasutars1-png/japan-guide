// 楽しさ版：カテゴリ設定（mockup の配色・絵文字に一致）
// tags は「カテゴリにもとづく編集タグ」。設備・事実の断定ではない。
export const CATS = [
  { key:"あそび場・体験", emoji:"🎡", svg:"/cat/asobi.svg",   tile:"#FFE7DE", grad:"linear-gradient(135deg,#FF9A76,#F0603D)", tags:["室内","雨の日OK"], ageMin:0, indoor:true },
  { key:"動物とふれあう", emoji:"🦁", svg:"/cat/animal.svg",  tile:"#E4F5EC", grad:"linear-gradient(135deg,#5BC7A0,#22A6A0)", tags:["動物"],           ageMin:0, indoor:false },
  { key:"学ぶ・科学館",   emoji:"🔬", svg:"/cat/science.svg", tile:"#E7F1FB", grad:"linear-gradient(135deg,#6FB1F0,#3E7FD0)", tags:["学ぶ","雨の日OK"], ageMin:2, indoor:true },
  { key:"公園でのびのび", emoji:"🌳", svg:"/cat/park.svg",    tile:"#EAF7F6", grad:"linear-gradient(135deg,#7BC96F,#4CA64C)", tags:["屋外","のびのび"], ageMin:0, indoor:false },
  { key:"水あそび",       emoji:"💧", svg:"/cat/water.svg",   tile:"#E6F6FA", grad:"linear-gradient(135deg,#4FD1C5,#2AA6B8)", tags:["水あそび","夏"],   ageMin:0, indoor:false },
  { key:"美術・文化",     emoji:"🎨", svg:"/cat/art.svg",     tile:"#FBEBF0", grad:"linear-gradient(135deg,#E58FB0,#C86A93)", tags:["アート","雨の日OK"], ageMin:2, indoor:true },
  { key:"観光・名所",     emoji:"🏰", svg:"/cat/sight.svg",   tile:"#F0ECFB", grad:"linear-gradient(135deg,#A99BE0,#7C6BC0)", tags:["おでかけ"],       ageMin:0, indoor:false },
];

const BY_KEY = Object.fromEntries(CATS.map(c => [c.key, c]));
const FALLBACK = { key:"観光・名所", emoji:"📍", tile:"#F0ECFB", grad:"linear-gradient(135deg,#A99BE0,#7C6BC0)", tags:["おでかけ"], ageMin:0, indoor:false };

export const catOf = (key) => BY_KEY[key] || FALLBACK;

// まとめLP（特集）定義：データ駆動フィルタ
export const FEATURES = [
  { slug:"rainy-indoor", title:"雨の日でも遊べる屋内スポット", tag:"雨でも安心",
    grad:"linear-gradient(135deg,#6FB1F0,#3E7FD0)",
    lead:"天気を気にせず遊べる、屋内中心のおでかけ先を集めました。",
    filter:(s,c)=>c.indoor },
  { slug:"baby-ok", title:"0〜2歳と行けるおでかけ先", tag:"赤ちゃん歓迎",
    grad:"linear-gradient(135deg,#FF9A76,#F0603D)",
    lead:"ねんね・よちよち期でも楽しみやすい、のびのび系・ふれあい系を中心に。",
    filter:(s,c)=>c.ageMin<=1 },
  { slug:"science-museum", title:"科学館・博物館めぐり", tag:"学べる",
    grad:"linear-gradient(135deg,#5BC7A0,#1F9488)",
    lead:"見て・触れて学べる、雨の日にもうれしい学び系スポット。",
    filter:(s,c)=>s.cat==="学ぶ・科学館" },
  { slug:"water-play", title:"千葉の水あそびスポット", tag:"夏のおすすめ",
    grad:"linear-gradient(135deg,#4FD1C5,#2AA6B8)",
    lead:"夏のおでかけや水遊びデビューに。水あそびが楽しめる場所。",
    filter:(s,c)=>s.cat==="水あそび" },
];
