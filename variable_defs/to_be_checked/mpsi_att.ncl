;
; Requires: va:*3*,ps:*2*s
;

info = True
info@derived = True

info@long_name="Zonal Mean Meridional Streamfunction"
info@units="kg m/s"
info@vcp_cnlvl=(/-20,-15,-10,-5,0,5,10,15,20,25,30,40,50,60,70/)*2.e9 ; U(ua)
info@vcp_dcnlvl=(/-18,-15,-12,-9,-6,-3,-1,0,1,3,6,9,12,15,18/)*2.e9
info@vcp_ptop=6e-4
info@vcp_LogScale = True

info@scp_cnlvl=(/-20,-15,-10,-5,0,5,10,15,20,25,30,40,50,60,70/)*2.e9 ; U(ua)
info@scp_dcnlvl=(/-18,-15,-12,-9,-6,-3,-1,0,1,3,6,9,12,15,18/)*2.e9

info@pcp_cnlvl=(/-20,-15,-10,-5,0,5,10,15,20,25,30,40,50,60,70/)*2.e9 ; U(ua)
info@pcp_dcnlvl=(/-18,-15,-12,-9,-6,-3,-1,0,1,3,6,9,12,15,18/)*2.e9

info@acp_cnlvl=(/-20,-15,-10,-5,0,5,10,15,20,25,30,40,50,60,70/)*2.e9 ; U(ua)
info@acp_dcnlvl=(/-18,-15,-12,-9,-6,-3,-1,0,1,3,6,9,12,15,18/)*2.e9

info@sdp_cnlvl=(/-18,-15,-12,-9,-6,-3,-1,0,1,3,6,9,12,15,18/)*2.e9
info@rgb_file = "red-blue.rgb"

info@ts_latrange = (/-25,25/)
info@ts_levrange = (/1000,200/)
info@ts_anom = False



undef("calculate")
function calculate(index [1] : integer,
                   variable [1] : string,
                   field_number [1] : string)
;;                 return_val [1] : logical
;; Arguments:
;;    index    - index to current infile defined in the 'temp_ncl_code/filesinfo'-file
;;    variable - logical with releveant variable as string attribute
;;    field_number  - string with field number classification
;; Return value:
;;    data_new - logical
local tmpV, tmpPS, i, dumV, dumPS, vt2b, pPa, p2Pa, psPa, lat, zmpsi
begin
  data_new = True
  tmpV = read_data(index,"va","*3*")
  tmpPS = read_data(index,"ps","*2*s")

  do i=0,dimsizes(models@name)-1

  dumV = extract_data(index,tmpV,-1,0,0)
  dumPS = extract_data(index,tmpPS,-1,0,0)

;  printVarSummary(dumV)
;  printVarSummary(dumPS)

  pPa   = dumV&plev*100.     ; make Pa
  pPa!0 = "plev"
  pPa&plev = dumV&plev
  if (pPa(0).lt.pPa(1)) then
    vt2b = dumV
    p2Pa = pPa
  else
    vt2b = dumV(:,::-1,:,:)    ; reverse the "lev" order to top-to-bottom
    p2Pa = pPa(::-1)
  end if

;  vt2b  = dumV(:,{10:1000},:,:)    ; clip from 10-1000 hpa
;  pPa   = dumV&plev({10:1000})*100.     ; reverse and make Pa


  psPa  = dumPS*100.          ; make Pa
  lat = dumV&lat

;  print(p2Pa)

;reverse vertical levels (so top - bottom)
  zmpsi = zonal_mpsi_Wrap(vt2b(:,{50:1000},:,:),lat,p2Pa({50:1000}),psPa)   ; zmpsi(ntim,klev,nlat)

;  printVarSummary(zmpsi)

  zmpsi@long_name = info@long_name
  zmpsi@units = info@units
  add_data(index,data_new,zmpsi)

  delete(zmpsi)
  delete(lat)
  delete(psPa)
  delete(pPa)
  delete(p2Pa)
  delete(dumV)
  delete(dumPS)
  delete(vt2b)

  delete(tmpV)
  delete(tmpPS)

  return(data_new)
end
