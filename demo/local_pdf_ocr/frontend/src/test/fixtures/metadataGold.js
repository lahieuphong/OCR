// Hand-authored expected values for the three synthetic administrative documents.
// These labels predate OCR scoring; they are not taken from a PDF text layer or model output.
const blank = {
  docId:"",arcDocCode:"",maintenance:"",typeName:"",codeNumber:"",codeNotation:"",issuedDate:"",organName:"",subject:"",language:"",numberOfPage:"",inforSign:"",keyword:"",mode:"",confidenceLevel:"",autograph:"",format:"",process:"",riskRecovery:"",riskRecoveryStatus:"",description:"",isCan:"",
};
const common = {...blank, issuedDate:"08-10-2026",organName:"VĂN PHÒNG KIỂM THỬ",
  subject:"V/v kiểm thử trích xuất thông tin trên tài liệu tổng hợp, giữ nguyên tiếng Việt",language:"01",numberOfPage:"1",confidenceLevel:"02"};
export const SYNTHETIC_GOLD = {
  officialLetter: {...common,arcDocCode:"00103/TEST-CN",codeNumber:"00103",codeNotation:"TEST-CN",typeName:"22"},
  decision: {...common,arcDocCode:"00002/QĐ-TEST",codeNumber:"00002",codeNotation:"QĐ-TEST",typeName:"02"},
  resolution: {...common,arcDocCode:"00321/NQ-TEST",codeNumber:"00321",codeNotation:"NQ-TEST",typeName:"01"},
};
