// Hand-authored fictional text and geometry, independent of user documents/OCR.
import {documentFromRows} from "./administrativeDocuments.js";
const parts=["Quy định việc tiếp nhận hồ sơ đến đơn vị kiểm thử theo Nghị định số 05/2020/NĐ-QA",
  "ngày 12 tháng 8 năm 2020 và Nghị định số 18/2024/NĐ-QA để phối hợp thực hiện",
  "nhiệm vụ được giao trong giai đoạn thí điểm và công tác quản lý hồ sơ",
  "tại cơ quan, đơn vị trực thuộc trên địa bàn thử nghiệm"];
export const STAMP_TEST_SUBJECT=parts.join(" ");
// merged=true: the stamp's date cell read on the subject's first line (split off by the extractor);
// merged="mixed": the cell's text holds a word ("giờ") and cannot be separated from the subject.
export const MERGED_PREFIX={true:"Ngày: 03/02/2025, ",mixed:"Ngày: 03/02/2025 giờ 9, "};
export function stampSubjectDocument({native=false,stamp=false,merged=false,sourcePages=6,code="00042/2025/NĐ-QA"}={}) {
  const rows=[["Ký bởi: Cơ quan thử nghiệm",350,5,585,18],["Thời gian ký: 02/03/2025",350,20,585,32],
    ["ỦY BAN NHÂN DÂN TỈNH KIỂM THỬ",45,72,280,88],["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",285,72,585,88],
    ["Độc lập - Tự do - Hạnh phúc",330,92,570,108],[`Số: ${code}`,90,120,270,136],
    ["Nơi thử nghiệm, ngày 14 tháng 2 năm 2025",300,120,585,136],["NGHỊ ĐỊNH",230,150,365,168],
    ...(stamp ? [["ĐẾN",5,166,90,181],["Giờ: C",5,185,90,198]] : []),
    ...parts.map((text,i)=>[merged&&i===0 ? MERGED_PREFIX[merged]+text : text,merged&&i===0 ? 40 : 99,175+i*20,555,190+i*20]),
    ["Căn cứ Luật Tổ chức cơ quan thử nghiệm;",45,280,555,296],["Điều 1. Nội dung quy định thử nghiệm.",45,310,555,326]];
  const raw=documentFromRows(rows,{method:native ? "native_text" : "vietocr_ocr"}),page=raw.pages[0];
  page.coordinate_system=native ? "pdf_points" : "raster_pixels";page.roi=[0,0,page.width,page.height*.45];
  page.lines.forEach((line,index)=>{line.geometry_source=native ? "native_text" : "vietocr_ocr";if(index<2)line.metadata_excluded_reason="electronic_signature";});
  return {...raw,method:"metadata_fast",source:native ? "header_native_text" : "header_ocr",used_ocr:!native,
    source_page_count:sourcePages,partial_result:true,inspected_pages:[1],processed_pages:native ? [] : [1],
    fast_metadata:{header_complete:true,needs_review:!native,reasons:[],roi_attempts:1,native_header_usable:native,roi_limit_reached:false}};
}
