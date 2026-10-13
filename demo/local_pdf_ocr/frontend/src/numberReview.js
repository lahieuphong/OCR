/** Opt-in, read-only header-number review suggestions.
 *
 * A candidate is not ground truth. Detection uses baseline OCR text and
 * page-1 coordinates ONLY; it never uses PDF filenames, human labels or
 * alternative recognizer predictions. The model's OCR text remains intact.
 */
const PREFIX=/^\s*s[ốo]\s*[:.\-]\s*/iu;
const DATE=/\bngày\s*\d{1,2}\s+tháng\s*\d{1,2}/iu;
// Require a digit BEFORE the first slash. This excludes labels such as\n// 'V/v kết thúc thực hiện Đề án' aligned with the document dateline.\nconst MAYBE_SERIAL_BEFORE_SLASH=/[0-9]/u;

export const REASONS={
  non_digit_serial:"Có chữ cái trong phần số trước dấu /",
  split_digits:"Khoảng trắng nằm giữa các chữ số",
  empty_serial:"Phần số văn bản bị bỏ trống",
  geometry_possible_number:"Có dòng tại vị trí số văn bản nhưng OCR không đọc được tiền tố Số:",
  number_field_not_located:"Không định vị được dòng số văn bản: cần xem toàn bộ trang 1",
};

function bounds(line){
  if(!Array.isArray(line?.polygon)||line.polygon.length!==4||
     !line.polygon.every(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)))return null;
  const xs=line.polygon.map(p=>p[0]),ys=line.polygon.map(p=>p[1]);
  return {x0:Math.min(...xs),x1:Math.max(...xs),y0:Math.min(...ys),
          y1:Math.max(...ys),yc:(Math.min(...ys)+Math.max(...ys))/2};
}

function serialFlags(text){
  const match=String(text||"").match(PREFIX);
  if(!match)return [];
  const serial=text.slice(match[0].length).split("/",1)[0].trim();
  if(!serial)return ["empty_serial"];
  if(/^[0-9]+(?:\s+[0-9]+)+$/u.test(serial))return ["split_digits"];
  return /[A-Za-z]/u.test(serial)?["non_digit_serial"]:[];
}

function candidate(line, page, reason){
  return {
    page:1,line_index:line.line_index,text:line.text,polygon:line.polygon,
    width:page.width,height:page.height,reasons:reason,
    review_key:"p1_l"+line.line_index,
  };
}

function unlocated(page){
  return {
    page:1,line_index:null,text:"",polygon:null,width:page.width,height:page.height,
    reasons:["number_field_not_located"],review_key:"p1_unlocated",
  };
}

export function findNumberReviewCandidates(data){
  if(!data||data.used_ocr!==true||data.method!=="vietocr_ocr"||
     !Array.isArray(data.pages)||!data.pages.length)return [];
  const page=data.pages.find(p=>p.page===1);
  if(!page||!Number.isFinite(page.width)||!Number.isFinite(page.height)||
     page.width<=0||page.height<=0||!Array.isArray(page.lines))return [];
  const {width:W,height:H}=page;
  const topLeft=l=>{
    const b=bounds(l);
    return b&&b.x0>=0&&b.x0<.60*W&&b.x1<=W&&b.x1>b.x0&&
           b.y0>.045*H&&b.y0<.37*H&&b.y1<=H&&
           b.y1>b.y0&&(b.y1-b.y0)<.08*H;
  };
  const header=page.lines.filter(topLeft);
  const explicit=header.filter(l=>PREFIX.test(l.text||""));
  const flagged=explicit.filter(l=>serialFlags(l.text).length).map(l=>
    candidate(l,page,serialFlags(l.text)));

  // An already detected "Số:" suppresses geometry fallback. Otherwise
  // incorrectly treat legitimate title/reference lines as number fields.
  if(explicit.length)return flagged;

  const dateLines=page.lines.filter(l=>{
    const b=bounds(l);
    return b&&b.x0>.40*W&&b.x1<=W&&b.y0>=0&&b.y0<.38*H&&
           DATE.test(l.text||"");
  });

  // Conservative alignment: the candidate must be on the same row,
  // left of a right-hand date, AND still resemble a serial-number row.
  // Using both geometry and shape reduces false alerts from agency names.
  // A completely unreadable/missing line gets a page-level warning instead.
  const aligned=header.filter(l=>{
    const b=bounds(l);
    const beforeSlash=String(l.text||"").split("/",1)[0].slice(0,24);
    return MAYBE_SERIAL_BEFORE_SLASH.test(beforeSlash)&&dateLines.some(d=>{
      const date=bounds(d);
      return b.x1<date.x0&&Math.abs(b.yc-date.yc)<.024*H;
    });
  });
  if(aligned.length){
    return aligned.map(l=>candidate(l,page,["geometry_possible_number"]))
      .sort((a,b)=>(a.line_index??1e6)-(b.line_index??1e6));
  }
  return [unlocated(page)];
}
