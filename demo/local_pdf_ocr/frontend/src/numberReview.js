/** Client-only, experimental header-number REVIEW TRIAGE.
 * Never uses ground-truth text, filenames, or editable notes to flag. */
const PREFIX=/^\s*s[ốo]\s*[:.\-]\s*/iu;
const DATE=/\bngày\s*\d{1,2}\s+tháng\s*\d{1,2}/iu;
export const REASONS={
  non_digit_serial:"Có chữ cái trong phần số trước dấu /",
  split_digits:"Khoảng trắng nằm giữa các chữ số",
  empty_serial:"Phần số văn bản bị bỏ trống",
  geometry_possible_number:"Có dòng ở vị trí số văn bản nhưng OCR không đọc được tiền tố Số:",
  number_field_not_located:"Chưa định vị được số văn bản; cần xem ảnh gốc",
};
const coord=(line)=>Array.isArray(line?.polygon)&&line.polygon.length===4&&
 line.polygon.every(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite));
const box=(line)=>{const x=line.polygon.map(p=>p[0]),y=line.polygon.map(p=>p[1]);return {x0:Math.min(...x),x1:Math.max(...x),y0:Math.min(...y),y1:Math.max(...y),yc:(Math.min(...y)+Math.max(...y))/2};};
function serialFlags(text){
  const m=String(text||"").match(PREFIX);if(!m)return [];
  const serial=String(text).slice(m[0].length).split("/")[0].trim();
  if(!serial)return ["empty_serial"];
  if(/^[0-9]+(?:\s+[0-9]+)+$/u.test(serial))return ["split_digits"];
  return /[A-Za-z]/u.test(serial)?["non_digit_serial"]:[];
}
export function findNumberReviewCandidates(data) {
  if(!data||data.used_ocr!==true||data.method!=="vietocr_ocr"||
     !Array.isArray(data.pages)||!data.pages.length)return [];
  const first=data.pages.find(p=>p.page===1);
  if(!first||!Number.isFinite(first.width)||!Number.isFinite(first.height)||
     first.width<=0||first.height<=0||!Array.isArray(first.lines))return [];
  const W=first.width,H=first.height;
  const nearHeader=l=>{
    if(!coord(l))return false;
    const r=box(l);
    return r.x0>=0&&r.x0<.60*W&&r.x1<=W&&r.y0>.045*H&&
      r.y0<.37*H&&(r.y1-r.y0)<.08*H;
  };
  const lines=first.lines.filter(nearHeader);
  const prefix=lines.filter(l=>PREFIX.test(l.text||""));
  const dates=first.lines.filter(l=>coord(l)&&DATE.test(l.text||"")&&box(l).x0>.40*W
                                   &&box(l).y0<.38*H);
  // If OCR misreads "Số:", align a left-half line with a right-hand
  // dateline. This is a CANDIDATE warning, never inferred text replacement.
  const nearDates=lines.filter(l=>dates.some(d=>{
    const a=box(l),b=box(d);
    return a.x1<b.x0&&Math.abs(a.yc-b.yc)<.024*H;
  }));
  const selected=new Map();
  for(const line of prefix){
    const flags=serialFlags(line.text);
    if(flags.length)selected.set(line.line_index,{
      page:1,line_index:line.line_index,text:line.text,polygon:line.polygon,
      width:W,height:H,reasons:flags,review_key:"p1_l"+line.line_index,
    });
  }
  if(!prefix.length){
    for(const line of nearDates){
      selected.set(line.line_index,{
        page:1,line_index:line.line_index,text:line.text,polygon:line.polygon,
        width:W,height:H,reasons:["geometry_possible_number"],
        review_key:"p1_l"+line.line_index,
      });
    }
  }
  // No detected prefix and no clear horizontal alignment MUST NOT mean
  // "all good": offer page-level manual check without fabricating a crop.
  if(!prefix.length&&!nearDates.length)selected.set(-1,{
    page:1,line_index:null,text:"",polygon:null,width:W,height:H,
    reasons:["number_field_not_located"],review_key:"p1_unlocated",
  });
  return [...selected.values()].sort((a,b)=>(a.line_index??1e6)-(b.line_index??1e6));
}
