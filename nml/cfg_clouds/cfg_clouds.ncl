diag_script_info = True

; --- multi-model mean parameters -----------------------------
; calculate multi-model mean?
; valid options: True, False
diag_script_info@calcmm = True

; --- time averaging ---
diag_script_info@timemean = "annualclim"   ; options: 1) annualclim (1 plots: annual mean)
                                           ;          2) seasonalclim (4 plots: DJF, MAM, JJA, SON)

; target grid for regridding: use grid of reference model
; (valid options are: "ref", "coarsest", "finest", "1x1")
diag_script_info@grid = "ref"

; reference model (to be skipped when calculating the multi-model mean)

if (variables(0).eq."lwp") then
    diag_script_info@ref_model = (/"UWisc"/)
else if (any(variables(0).eq.(/"rlutcs", "rlut", "rsutcs", "rsut","SW_CRE","LW_CRE","NET_CRE"/))) then
    diag_script_info@ref_model = (/"CERES-EBAF"/)
else if (any(variables(0).eq.(/"clt"/))) then
    diag_script_info@ref_model = (/"MODIS"/)
else if (any(variables(0).eq.(/"clivi"/))) then
    diag_script_info@ref_model = (/"MODIS-CFMIP"/)
else if (any(variables(0).eq.(/"pr","pr-mmday"/))) then
    diag_script_info@ref_model = (/"GPCP-SG"/)
end if
end if
end if
end if
end if
; -------------------------------------------------------------
