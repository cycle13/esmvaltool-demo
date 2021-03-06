"""
Basic implementation for diagnostics into ESMValTool
"""

"""
Used modules
"""
#import code
import numpy as np
import os
#import matplotlib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from netCDF4 import Dataset

#global installation
from geoval.core.data import GeoData
from geoval.core.mapping import *
import extended_data
from esmval_lib import ESMValProject
#from GeoData_mapping import *

#import ConfigParser
import csv
import imp
import shapefile as shp
import glob
import math
import tempfile
import datetime
#from dateutil.relativedelta import relativedelta
import subprocess
import fnmatch

from scipy import stats
from cdo import Cdo

#All packages checked

#ignored GLOBAL values
#TODO verbosity_level
#TODO exit_on_warning
#TODO debuginfo

#TODO max_data_filesize
#TODO max_data_blocksize

#TODO write_plots
#TODO write_netcdf
#TODO write_plot_vars

#TODO force_processing

class Diagnostic(object):
    """
    Basic class to implement any kind of diagnostic
    """
    def __init__(self, **kwargs):
        super(Diagnostic, self).__init__(**kwargs)
        """
        Default values to experiment with the diagnostics
        """
        self._project_info={}
        self._mod_type = 'model' 
        self._ref_type = 'reference' 
        self._plot_dir='.' + os.sep
        self._work_dir='.' + os.sep

        self._vartype = 'some variable' #default value as there must be one
        self.output_type = 'png'  # default ouput file type
        self.overview=False
        self._regions=None
        self._changed=False
        

    def _get_output_rootname(self):
        """
        get unique output filename as function of model name and observation name
        """

        name_parts=self._mod_file.split("/")[-1].split(".")[0].split("_")
        self.modname = "_".join(name_parts[i] for i in [0,3,2,4])
        self.refname = "ESACCI"#self._ref_type

        return self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + self.refname + '_' + self.modname


    def set_info(self,project_info,model,var,ref_file,mod_file,cfg):
        """
        gather information for diagnostic
        """
        
        def getVarFromFile(filename):
            """
            routine to read cfg file
            """
            f = open(filename)
            self.cfg = imp.load_source('cfg', '', f)
            f.close()
            
        
        getVarFromFile(cfg)
                       
        self._project_info=project_info

# A_laue_ax+
#        self._plot_dir=project_info.get('GLOBAL')['plot_dir']
        E = ESMValProject(project_info)
        plot_dir = E.get_plot_dir()
        diag_script = E.get_diag_script_name()
        plot_dir = plot_dir + os.sep + diag_script + os.sep
        E.ensure_directory(plot_dir)
        self._plot_dir=plot_dir
        self.E = E
# A_laue_ax-
        self._work_dir=project_info.get('GLOBAL')['wrk_dir']
        self._climo_dir=project_info.get('GLOBAL')['climo_dir']
        self._mod_line=model.split_entries()
        self._field_type=project_info['RUNTIME']['derived_field_type']
        self.var=var
        allvars=[x.var==var for x in project_info['RUNTIME']['currDiag'].variables]
        whichvar=[i for i, x in enumerate(allvars) if x][0]
        self._ref_type = project_info['RUNTIME']['currDiag'].variables[whichvar].ref_model #TODO: make this var!
        self._mod_type=project_info['RUNTIME']['project']
        
        self.output_type = project_info['GLOBAL']['output_file_type']

        if var == 'sm':
            self._vartype = 'soil moisture'
            self._ref_file= ref_file
        elif var == 'ts' or var == 'tos':
            self._vartype = 'sea surface temperature'
            self._ref_file= ref_file
        elif var == 'shrubNtreeFrac': #TODO from cfg
            self._vartype = 'shrub and tree'
            self._ref_file= ref_file
        elif var == 'baresoilFrac':
            self._vartype = 'bare soil'
            self._ref_file= ref_file
            
            if self.cfg.cmap_globmeants[-3:-1] == "_r":
                self.cfg.cmap_globmeants=self.cfg.cmap_globmeants[:-2]
            else:
                self.cfg.cmap_globmeants=self.cfg.cmap_globmeants+"_r"
            
        elif var == 'grassNcropFrac':
            self._vartype = 'grass and crop'
            self._ref_file= ref_file
        else:
            assert False, 'This variable is not implemented yet!'


        self._mod_file=mod_file

        self._get_output_rootname()
        
        if self.cfg.regionalization:
            self._reg_file="./diag_scripts/aux/LMU_ESACCI-diagnostics/Shapefiles" + os.sep + self.cfg.shape
            self._load_regionalization_shape()
        

    def _write_loading_header(self):
        print('*****************************')
        print('Loading data for diagnostics of %s from %s' % (self._vartype.upper(), self._mod_file.split(os.sep)[-1]))
        print('*****************************')

    def load_data(self):
        """
        load model and observation data
        actual implementation needs to be part of child class
        """
        
        self._write_loading_header()
        
        if not self._changed:
            self._start_time,self._stop_time = None,None
        
        self._load_model_data()
        self._load_observation_data()
        
        # compatible time range
        self._start_time,self._stop_time,self._changed=self._adjust_time_range(scale="month") #if self._project_info['RUNTIME']['currDiag'].get_variables()[0] in ['natural_grass', 'managed_grass_and_crops', 'bare_soil', 'shrubs', 'forest','lc'] else "month")         
        
        if 'start_year' in self.cfg.__dict__.keys():
            if self.cfg.start_year>self._start_time.year:
                self._start_time=self._start_time.replace(year=self.cfg.start_year,month=01,day=01)
                self._changed=True
        if 'stop_year' in self.cfg.__dict__.keys():
            if self.cfg.stop_year<self._stop_time.year:
                self._stop_time=self._stop_time.replace(year=self.cfg.stop_year,month=12,day=31)
                self._changed=True     
        
        if self._changed and not (self.var in ["baresoilFrac","grassNcropFrac","shrubNtreeFrac"]):
            #reorganize data
            self._mod_data.apply_temporal_subsetting(self._start_time, self._stop_time)
            self._ref_data.apply_temporal_subsetting(self._start_time, self._stop_time)
        
        # compatible spatial masks
        self._check_mask()
        
        self._ts=[x.date() for x in self._mod_data.date]
        
        if 'write_preprocessed_data' in self.cfg.__dict__.keys():
            if self.cfg.write_preprocessed_data:
                    self._save_p_data()
                
#    def _save_p_data(self):
#        """ 
#        write data to harddrive to make it accessible for other diagnostics (such as perfmetrics)
#        """
#        
#        new_time=str(self._start_time.year) + "01" + "-" + str(self._stop_time.year) + "12" + ".nc"
#
#        ref_out_name=self._ref_file
#        ref_out_name=ref_out_name.split("_" + self.cfg.ref_var.upper() + "_")
#        temp=ref_out_name[-1].split(".")
#        temp_s1="_" + str(self._start_time.year) + "01" + "-" + str(self._stop_time.year) + "12"
#        temp=[temp[0] + temp_s1] + [temp[-1]]
#        ref_out_name[-1]=".".join(temp)
#        ref_out_name=("_" + self.cfg.newvar.upper() + "_").join(ref_out_name)
#        ref_out_name=ref_out_name.split("_" + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + ".")
#        ref_out_name=("_" + self.cfg.newvar + ".").join(ref_out_name)
#        
#        mod_out_name=self._mod_file
#        mod_out_name=mod_out_name.split(os.sep + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + "_")
#        mod_out_name[1]=mod_out_name[1].split("_")
#        mod_out_name[1][-1]=new_time
#        mod_out_name[1]="_".join(mod_out_name[1])
#        mod_out_name=(os.sep + self.cfg.newvar + "_").join(mod_out_name)        
#
#
##        print(self._ref_data.time)
##        print([self._ref_data.time[0]]+list(self._ref_data.time[0]+np.cumsum(np.repeat(30.5,len(self._ref_data.time)-1))))
##        print(type(self._ref_data.time))
#    
#        print(self._ref_data.time[0])
#        print(self._mod_data.time[0])
#
#
##        self._ref_data.time=np.asarray([self._ref_data.time[0]-7]+list(self._ref_data.time[0]-7+np.cumsum(np.repeat(30.5,len(self._ref_data.time)-1))))
##        self._mod_data.time=np.asarray([self._mod_data.time[0]]+list(self._mod_data.time[0]+np.cumsum(np.repeat(30.5,len(self._mod_data.time)-1))))
#
#        
#        if not os.path.isfile(ref_out_name):
#            self._ref_data.save(ref_out_name+"tmp1",self.cfg.newvar)
#            cdo=Cdo()
#            cdo.setreftime("1850-01-01,00:00:00",input=ref_out_name+"tmp1",output=ref_out_name,options='-L -f nc4 -b F32')
##            cdo.invertlat(input=ref_out_name+"tmp2",output=ref_out_name,options='-L -f nc4 -b F32')
#            subprocess.call(['rm',ref_out_name+"tmp1"])
##            subprocess.call(['rm',ref_out_name+"tmp2"])
#        else: 
#            print(ref_out_name + " already available!")
#            
#        if not os.path.isfile(mod_out_name):   
#            self._mod_data.save(mod_out_name,self.cfg.newvar)
#        else:
#            print(mod_out_name + " already available!")
#            
#        self.cfg.climo=True
#        
#        if 'climo' in self.cfg.__dict__.keys():
#            if self.cfg.climo:
#            
#                reformat_ref_out=ref_out_name.split(os.sep)[-1]
#                reformat_ref_out=reformat_ref_out.split("_")
#                temp=reformat_ref_out[1]
#                reformat_ref_out[1]=reformat_ref_out[2]
#                reformat_ref_out[2]=temp
#                reformat_ref_out="_".join(reformat_ref_out)
#                
#                
#                reformat_mod_out=self._mod_file
#                reformat_mod_out=reformat_mod_out.split(os.sep + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + "_")
#                reformat_mod_out=reformat_mod_out[1].split("_")
#                temp=reformat_mod_out[-1].split(".")
#                temp_s1=temp[0].split("-")
#                temp_s1[0]=temp_s1[0]+"01"
#                temp_s1[1]=temp_s1[1]+"12"
#                temp[0]="-".join(temp_s1)
#                reformat_mod_out[-1]=".".join(temp)
#                reformat_mod_out="_".join([self._mod_type,reformat_mod_out[0],reformat_mod_out[2],reformat_mod_out[1],reformat_mod_out[3],self._field_type,self.cfg.newvar,new_time])
#        
#        #                cdo=Cdo()
#        
#                ofile=self._climo_dir + ("" if self._climo_dir[-1]==os.sep else os.sep) + self.cfg.ref_data.split("_")[0] + os.sep + reformat_ref_out
#        #                cdo.ymonmean(input=ref_out_name,output=ofile)
#                subprocess.call(['cp',ref_out_name,ofile])
#                
#                ofile=self._climo_dir + ("" if self._climo_dir[-1]==os.sep else os.sep) + self._project_info['RUNTIME']['project'] + os.sep + reformat_mod_out
#        #                cdo.ymonmean(input=mod_out_name,output=ofile)
#                subprocess.call(['cp',mod_out_name,ofile])
#                
#        print("   Data written!")
#
#    def _save_p_data(self):
#        """ 
#        write data to harddrive to make it accessible for other diagnostics (such as perfmetrics)
#        """
#        
#        new_time=str(self._start_time.year) + "01" + "-" + str(self._stop_time.year) + "12" + ".nc"
#
#        ref_out_name=self._ref_file
#        ref_out_name=ref_out_name.split("_" + self.cfg.ref_var.upper() + "_")
#        temp=ref_out_name[-1].split(".")
#        temp_s1="_" + str(self._start_time.year) + "01" + "-" + str(self._stop_time.year) + "12"
#        temp=[temp[0] + temp_s1] + [temp[-1]]
#        ref_out_name[-1]=".".join(temp)
#        ref_out_name=("_" + self.cfg.newvar.upper() + "_").join(ref_out_name)
#        ref_out_name=ref_out_name.split("_" + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + ".")
#        ref_out_name=("_" + self.cfg.newvar + ".").join(ref_out_name)
#        
#        mod_out_name=self._mod_file
#        mod_out_name=mod_out_name.split(os.sep + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + "_")
#        mod_out_name[1]=mod_out_name[1].split("_")
#        mod_out_name[1][-1]=new_time
#        mod_out_name[1]="_".join(mod_out_name[1])
#        mod_out_name=(os.sep + self.cfg.newvar + "_").join(mod_out_name)               
#        
#        if not os.path.isfile(ref_out_name):
#            self._ref_data.save(ref_out_name,self.cfg.newvar)
#        else: 
#            print(ref_out_name + " already available!")
#            
#        if not os.path.isfile(mod_out_name):   
#            self._mod_data.save(mod_out_name,self.cfg.newvar)
#        else:
#            print(mod_out_name + " already available!")
#            
#        reformat_ref_out=ref_out_name.split(os.sep)[-1]
#        reformat_ref_out=reformat_ref_out.split("_")
#        temp=reformat_ref_out[1]
#        reformat_ref_out[1]=reformat_ref_out[2]
#        reformat_ref_out[2]=temp
#        reformat_ref_out="_".join(reformat_ref_out)
#        
#        reformat_mod_out=self._mod_file
#        reformat_mod_out=reformat_mod_out.split(os.sep + self._project_info['RUNTIME']['currDiag'].get_variables()[0] + "_")
#        reformat_mod_out=reformat_mod_out[1].split("_")
#        temp=reformat_mod_out[-1].split(".")
#        temp_s1=temp[0].split("-")
#        temp_s1[0]=temp_s1[0]+"01"
#        temp_s1[1]=temp_s1[1]+"12"
#        temp[0]="-".join(temp_s1)
#        reformat_mod_out[-1]=".".join(temp)
#        reformat_mod_out="_".join([self._mod_type,reformat_mod_out[0],reformat_mod_out[2],reformat_mod_out[1],reformat_mod_out[3],self._field_type,self.cfg.newvar,new_time])
#
#        ofile=self._climo_dir + ("" if self._climo_dir[-1]==os.sep else os.sep) + self.cfg.ref_data.split("_")[0] + os.sep + reformat_ref_out
#        subprocess.call(['cp',ref_out_name,ofile])
#        
#        ofile=self._climo_dir + ("" if self._climo_dir[-1]==os.sep else os.sep) + self._project_info['RUNTIME']['project'] + os.sep + reformat_mod_out
#        subprocess.call(['cp',mod_out_name,ofile])
#            
#        print("   Data written!")


    def _load_regionalization_shape(self):
        """
        loading model data
        """
        assert False, 'This routine needs to be implemented in child class!'
        
    def _load_model_data(self):
        """
        loading model data
        """
        assert False, 'This routine needs to be implemented in child class!'

    def _load_observation_data(self):
        """
        loading reference data
        """
        assert False, 'This routine needs to be implemented in child class!'
        
    def _check_mask(self):
        """
        adjusting mask
        """
        assert False, 'This routine needs to be implemented in child class!'
        
    def _adjust_time_range(self):
        """
        adjusting time range
        """
        assert False, 'This routine needs to be implemented in child class!'

    def run_diagnostic(self):
        """
        run diagnostics
        """
        assert False, 'This routine needs to be implemented in child class!'
 

class BasicDiagnostics(Diagnostic):
    """
    class to implement basic diagnostics, like e.g. global means, global differences, RMSD etc.
    """
    def __init__(self, **kwargs):
        super(BasicDiagnostics, self).__init__(**kwargs)
        self._plot_parameters()
        
    def _plot_parameters(self):
        """ 
        set plotting parameters 
        could be read in, but I think static is better!        
        """
        
        
        self.plot_dpi=300
        self.plot_backend='cartopy'
        
        self.plot_nclasses=10
        self.plot_cborientation='vertical'
        self.plot_cbshow=True
        self.plot_tfont=14
        
        
    def _load_model_data(self):
        """ load model data """
        assert False, 'Not supported without specific varaiable!'

    def _load_observation_data(self):
        """ load obs data """
        assert False, 'Not supported without specific varaiable!'


    def _load_cmip_generic(self,filename, k):
        """
        Parameters
        ----------
        k : str
            key describing which data to load. Should be CF convention compliant
        """
# A_laue_ax+
        self.E.add_to_filelist(filename)
# A_laue_ax-
        if '_start_time' in self.__dict__.keys():
            if '_stop_time' in self.__dict__.keys():
                return GeoData(filename,k, read=True,start_time=self._start_time,stop_time=self._stop_time)
            else:
                return GeoData(filename,k, read=True,start_time=self._start_time)
        else:
            if '_stop_time' in self.__dict__.keys():
                return GeoData(filename,k, read=True,stop_time=self._stop_time)
            else:
                return GeoData(filename,k, read=True)

        
    def _load_cci_generic(self, filename,k):
        """
        Parameters
        ----------
        k : str
            key describing which data to load. Should be CF convention compliant
        """
# A_laue_ax+
        self.E.add_to_filelist(filename)
# A_laue_ax-
        if '_start_time' in self.__dict__.keys():
            if '_stop_time' in self.__dict__.keys():
                return GeoData(filename,k, read=True,start_time=self._start_time,stop_time=self._stop_time)
            else:
                return GeoData(filename,k, read=True,start_time=self._start_time)
        else:
            if '_stop_time' in self.__dict__.keys():
                return GeoData(filename,k, read=True,stop_time=self._stop_time)
            else:
                return GeoData(filename,k, read=True)

        
    def _load_shape_generic(self, filename):
        """
        load the specified shapefile
        """
        return shp.Reader(filename)
       
    def _check_mask(self):
        """ 
        mask adjustments 
        """
        if isinstance(self._mod_data.data,np.ma.core.MaskedArray):
            if isinstance(self._ref_data.data,np.ma.core.MaskedArray):
                mask=np.logical_or(self._ref_data.data.mask,self._mod_data.data.mask)
                self._mod_data.data.mask=mask
                self._ref_data.data.mask=mask
                print "both sets have masks, common mask produced"

# A_laue_ax+
                #code.interact(local=locals())
                ## open a new netCDF file for writing.
                #ncfile = Dataset('debug.nc','w') 
                ## create the x and y dimensions.
                #dims = np.shape(mask)
                #nx = dims[2]
                #ny = dims[1]
                #nt = dims[0]
                #ncfile.createDimension('x',nx)
                #ncfile.createDimension('y',ny)
                #ncfile.createDimension('t',nt)
                ## first argument is name of variable, second is datatype, third is
                ## a tuple with the names of dimensions.
                #data_ref = ncfile.createVariable('data_ref','i4',('t','y','x'))
                #data_mod = ncfile.createVariable('data_mod','i4',('t','y','x'))
                ## write data to variable.
                #data_ref[:] = self._ref_data.data.mask.astype(int)
                #data_mod[:] = self._mod_data.data.mask.astype(int)
                ## close the file.
                #ncfile.close()
# A_laue_ax-

            else:
                self._ref_data.data=np.ma.array(self._ref_data.data)
                self._ref_data.data.mask=self._mod_data.data.mask
                print "model data has mask, common mask produced"
        else:
            if isinstance(self._ref_data.data,np.ma.core.MaskedArray):
                self._mod_data.data=np.ma.array(self._mod_data.data)
                self._mod_data.data.mask=self._ref_data.data.mask
                print "reference data has mask, common mask produced"
            else:
                print "no data have masks"
        
    def _write_writing_header(self):
        print('*****************************')
        print('Writing diagnostics results for %s' % self._vartype.upper())
        print('*****************************')
        
    def _write_regionalization_header(self):
        print('*****************************')
        print('Calculating regionalization mask for %s' % self.cfg.shape.upper())
        print('*****************************')        

    def write_data(self,plot=True):
        """ write data """
        
        if self.cfg.regionalization and self._regions==None:
            self._write_regionalization_header()   
            self._regions=self._ref_data.get_regions(self._reg_shape,self.cfg.shapeNames-1)
            print("     Region names: " + ", ".join(self._regions.keys()))
        
        
        self._write_writing_header()
        
        if '_gmd_data' in self.__dict__.keys():
            self._plot_global_mean_difference()
            if self.cfg.regionalization:
                self._gmd_data.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._gmd_data.regionalized,'gmd',self.refname + '_' + self.modname)
        else:
            print 'No mean difference to plot!'
        if '_gmt_r_data' in self.__dict__.keys():
            self._plot_global_mean_timeseries(self.refname)
            if self.cfg.regionalization:
                self._gmt_r_data.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._gmt_r_data.regionalized,'gmt',self.refname)
        else:
            print 'No reference mean timeseries to plot!'
        if '_gmt_m_data' in self.__dict__.keys():
            self._plot_global_mean_timeseries(self.modname)
            if self.cfg.regionalization:
                self._gmt_m_data.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._gmt_m_data.regionalized,'gmt',self.modname)
        else:
            print 'No model mean timeseries to plot!'
        if '_stat_r_data' in self.__dict__.keys():
            self._write_portrait_statistic(self.refname)
        else:
            print 'No reference stats to write!'
        if '_stat_m_data' in self.__dict__.keys():
            self._write_portrait_statistic(self.modname)
        else:
            print 'No model stats to write!'
        if '_KT_corr' in self.__dict__.keys():    
            self._plot_trend_corr_maps(self._KT_corr,self._KT_pval)
            if self.cfg.regionalization:
                self._KT_corr.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._KT_corr.regionalized,'trend_correlation',self.refname + '_' + self.modname)
        else:
            print 'No trend comparison to write!'
        if '_Sr' in self.__dict__.keys():   
            self._plot_trend_maps(self._Sr,self._Pr,self.refname)
            if self.cfg.regionalization:
                self._Sr.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._Sr.regionalized,'trend',self.refname)
        else:
            print 'No reference trend to write!'
        if '_Sm' in self.__dict__.keys():
            self._plot_trend_maps(self._Sm,self._Pm,self.modname)
            if self.cfg.regionalization:
                self._Sm.get_shape_statistics(self._regions)
                self._write_shape_statistics(self._Sm.regionalized,'trend',self.modname)
        else:
            print 'No model trend to write!'
            
        if '_stat_m_data' in self.__dict__.keys() and '_stat_r_data' in self.__dict__.keys():
            if self.cfg.portrait:
                self.overview=True
                self._plot_portrait_comparison(self.refname,self.modname)
            else:
                print 'No portrait comparison to write!'
        else:
            print 'No portrait comparison to write!'

    def _adjust_time_range(self,scale="month"):
        """
        restrict data to common time
        currently only works for full months, maybe implement switch
        """
        
        changed=True
        
        if scale == "month":
            ref_start=self._ref_data.date[0]
            ref_stop=self._ref_data.date[-1]
            mod_start=self._mod_data.date[0]
            mod_stop=self._mod_data.date[-1]
        
            
            if (ref_start==mod_start and ref_stop==mod_stop): 
                changed=False
            
            #for monthly data:
            def month_end(dt):
                # Get the next month
                y, m = dt.year, dt.month
                if m == 12:
                    y += 1
                    m = 1
                else:
                    m += 1  
                
                return dt.replace(year=y, month=m, day=1, hour=0,minute=0,second=0) - datetime.timedelta(seconds=1)
            
            def month_start(dt):
                # Get the month before
                y, m = dt.year, dt.month
                if m == 1:
                    y -= 1
                    m = 12
                else:
                    m -= 1  
                
                return month_end(dt.replace(year=y, month=m, day=1)) + datetime.timedelta(seconds=1)
            
                    
            start=month_start(max(ref_start,mod_start))
            stop=month_end(min(ref_stop,mod_stop))      
            
            return start,stop,changed
            
        elif scale == "year":
            
            ref_start=self._ref_data.date[0]
            ref_stop=self._ref_data.date[-1]
            mod_start=self._mod_data.date[0]
            mod_stop=self._mod_data.date[-1]
            
            
            
            if (ref_start==mod_start and ref_stop==mod_stop): 
                changed=False
            
            #for yearly data:
            def year_end(dt):
                # Get the next year
                y=dt.year
                y += 1  
                
                return dt.replace(year=y, month=1, day=1, hour=0,minute=0,second=0) - datetime.timedelta(seconds=1)
            
            def year_start(dt):
                # Get the year before
                y=dt.year
                y -= 1  
                
                return year_end(dt.replace(year=y, month=1, day=1)) + datetime.timedelta(seconds=1)
            
                    
            start=year_start(max(ref_start,mod_start))
            stop=year_end(min(ref_stop,mod_stop))      
            
            return start,stop,changed
                    
    """
    Diagnostics
    """

    def run_diagnostic(self, globmeants=True, portrait=True, globmeandiff=True, trend=True):
        """
        running the diagnostics
        """      
        
        self._write_basic_diagnostic_header()
        
        if globmeants:
            self._global_mean_timeseries(self.refname)
            self._global_mean_timeseries(self.modname)
        if portrait:
            self._portrait_statistic(self.refname)
            self._portrait_statistic(self.modname)
        if globmeandiff:
            self._global_mean_difference()
        if trend:
            self._trend_analysis()
            
    def _write_basic_diagnostic_header(self):
        print('*****************************')
        print('Running diagnostics for %s' % self._vartype.upper())
        print('*****************************')


    def _global_mean_difference(self):
        """ calculating differences of global mean"""
        
        print('   global mean difference ...')

        self._gmd_data=self._mod_data.copy()
        self._gmd_data.label='global_mean_difference' + ' [' + self._ref_data.label + '-' + self._mod_data.label + ']'
        self._gmd_data.data=self._mod_data.timmean()-self._ref_data.timmean()
        self._gmdr_data=self._mod_data.copy()
        self._gmdr_data.label='relative_global_mean_difference' + ' [' + self._ref_data.label + '-' + self._mod_data.label + ']'
        self._gmdr_data.data=(self._mod_data.timmean()-self._ref_data.timmean())/self._ref_data.timmean()
        self._gmdr_data.unit="-"
            
            
    def _plot_global_mean_difference(self):
        """
        plot global mean difference
        """
        Map = SingleMap(self._gmd_data,
                        backend=self.plot_backend,
                        show_statistic=True,
                        stat_type='mean',
                        savefile=None,
                        ax=None,
                        show_unit=True)
        Map.plot(title= self.modname + " - " + self.refname + ' global mean difference',
                 show_zonal=False,
                 show_histogram=False,
                 show_timeseries=False,
                 nclasses=self.plot_nclasses,
                 colorbar_orientation=self.plot_cborientation,
                 show_colorbar=self.plot_cbshow, 
                 cmap='RdBu', 
                 vmin=min(self.cfg.mima_globmeandiff),
                 vmax=max(self.cfg.mima_globmeandiff), 
                 proj_prop=self.cfg.projection, 
                 ctick_prop={'ticks': None, 'labels': None},
                 drawparallels=True,
                 titlefontsize=self.plot_tfont)
        Map.figure.savefig(self._get_output_rootname() + '_gmd.' + self.output_type,
                           dpi=self.plot_dpi)
                           
        plt.close()

        #and     

        if '_gmt_r_data' in self.__dict__.keys() and '_gmt_m_data' in self.__dict__.keys():   
        
            f = plt.figure(figsize=(20,12))
            ax1 = f.add_subplot(221)
            ax2 = f.add_subplot(222)
            ax3 = f.add_subplot(223)
            ax4 = f.add_subplot(224)
    
            def submap_U(data,ax,cmap,ctick={'ticks': None, 'labels': None}):
                Map = SingleMap(data,
                            backend=self.plot_backend,
                            show_statistic=True,
                            stat_type='mean',
                            savefile=None,
                            ax=ax,
                            show_unit=True)
                Map.plot(title= data.label,
                     show_zonal=False,
                     show_histogram=False,
                     show_timeseries=False,
                     nclasses=self.plot_nclasses,
                     colorbar_orientation=self.plot_cborientation,
                     show_colorbar=self.plot_cbshow, 
                     cmap=cmap, 
                     vmin=min(self.cfg.mima_globmeants),
                     vmax=max(self.cfg.mima_globmeants), 
                     proj_prop=self.cfg.projection, 
                     ctick_prop=ctick,
                     drawparallels=True,
                     titlefontsize=self.plot_tfont)  
                     
            def submap_LL(data,ax,title,cmap,ctick={'ticks': None, 'labels': None}):
                Map = SingleMap(data,
                            backend=self.plot_backend,
                            show_statistic=True,
                            stat_type='mean',
                            savefile=None,
                            ax=ax,
                            show_unit=True)
                Map.plot(title= title,
                     show_zonal=False,
                     show_histogram=False,
                     show_timeseries=False,
                     nclasses=self.plot_nclasses,
                     colorbar_orientation=self.plot_cborientation,
                     show_colorbar=self.plot_cbshow, 
                     cmap=cmap, 
                     vmin=min(self.cfg.mima_globmeandiff),
                     vmax=max(self.cfg.mima_globmeandiff), 
                     proj_prop=self.cfg.projection, 
                     ctick_prop=ctick,
                     drawparallels=True,
                     titlefontsize=self.plot_tfont)
                     
            def submap_LR(data,ax,title,cmap,ctick={'ticks': None, 'labels': None}):
                Map = SingleMap(data,
                            backend=self.plot_backend,
                            show_statistic=True,
                            stat_type='mean',
                            savefile=None,
                            ax=ax,
                            show_unit=True)
                Map.plot(title= title,
                     show_zonal=False,
                     show_histogram=False,
                     show_timeseries=False,
                     nclasses=self.plot_nclasses,
                     colorbar_orientation=self.plot_cborientation,
                     show_colorbar=self.plot_cbshow, 
                     cmap=cmap, 
                     vmin=min(self.cfg.mima_globmeandiff_r),
                     vmax=max(self.cfg.mima_globmeandiff_r),  
                     proj_prop=self.cfg.projection, 
                     ctick_prop=ctick,
                     drawparallels=True,
                     titlefontsize=self.plot_tfont)
            
            
            submap_U(self._gmt_m_data, ax=ax1,cmap=self.cfg.cmap_globmeants)
            submap_U(self._gmt_r_data, ax=ax2,cmap=self.cfg.cmap_globmeants)
            submap_LL(self._gmd_data, ax=ax3,cmap='RdBu',title= "global mean difference \n" + self.modname + " - " + self.refname, ctick={'ticks': np.linspace(min(self.cfg.mima_globmeandiff),+max(self.cfg.mima_globmeandiff),11), 'labels': np.append(np.insert(np.linspace(min(self.cfg.mima_globmeandiff),+max(self.cfg.mima_globmeandiff),11).astype('string')[1:10],0,'< ' + str(min(self.cfg.mima_globmeandiff))),'> ' + str(max(self.cfg.mima_globmeandiff)))})
            submap_LR(self._gmdr_data, ax=ax4,cmap='RdBu',title= "relative global mean difference \n" + "(" + self.modname + " - " + self.refname + ") / " + self.refname,ctick={'ticks': np.linspace(min(self.cfg.mima_globmeandiff_r),max(self.cfg.mima_globmeandiff_r),11), 'labels': np.append(np.insert(np.linspace(min(self.cfg.mima_globmeandiff_r),max(self.cfg.mima_globmeandiff_r),11).astype('string')[1:10],0,'< ' + str(min(self.cfg.mima_globmeandiff_r))),'> ' + str(max(self.cfg.mima_globmeandiff_r)))})
            f.suptitle("")
    
            oname = self._get_output_rootname() + '_4plots_gmd.' + self.output_type
            if os.path.exists(oname):
                os.remove(oname)
            f.savefig(oname)
    
            plt.close(f.number)  # close figure for memory reasons!
            del f
        
    def _p_stat(self,D,ts):
            
        """ produce table """
        
        _min_data=D.data.min(axis=(1,2)).data
        _mean_data=D.fldmean()#data.mean(axis=1).mean(axis=1).data
        _max_data=D.data.max(axis=(1,2)).data
        
        D2=D.copy()
        D2.data=D2.data**2
        _std_data=np.sqrt((D2.fldmean()-_mean_data**2))
        
        _cov_data=_std_data/_mean_data
        _count=np.logical_not(D.data.mask).sum(axis=(1,2))

        return(np.vstack((ts, 
                          _min_data,
                          _mean_data,
                          _max_data,
                          _std_data,
                          _cov_data,
                          _count
                          ))
                      )

    def _portrait_statistic(self,name):
        """ calculating basic statistics """
        
        print('   portrait statistics ...')
            
        if name == self.refname:
            self._stat_r_data = self._p_stat(self._ref_data,self._ts)

        elif name == self.modname:
            self._stat_m_data = self._p_stat(self._mod_data,self._ts)
        else:
            assert False, 'data not expected'
            
    def _write_portrait_statistic(self,name):
        """ writing portrait statistic as csv """
        oname = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + name + '_stat.csv'
        if os.path.exists(oname):
            os.remove(oname)
        f=open(oname,'w')
        try:
            writer=csv.writer(f,quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(('date' , 'min' , 'mean' , 'max' , 'sd' , 'cov','count')) 
            writer.writerows(self._stat_r_data.T if name == self.refname else self._stat_m_data.T)
        finally:
            f.close()
            
    def _plot_portrait_comparison(self,refname,modname):  
        """ plotting portrait comparison """
        #plot spatially aggregated ts
        f = plt.figure()
        f.suptitle(refname + " and " + modname + ' spatial mean', fontsize=14)
        ax = f.add_subplot("111")
        ax.plot(self._ts,self._stat_m_data[2], linestyle='-',color="b",label=modname)
        ax.plot(self._ts,self._stat_r_data[2], linestyle='-',color="r",label=refname)
        plt.gcf().autofmt_xdate()
        plt.legend()
        ax.set_xlabel("")
        ax.set_ylabel('spatial mean ' + self._vartype + " ["+ self._mod_data.unit +"]")
        #ymin=min([np.array(self._stat_m_data[2]).min(),np.array(self._stat_r_data[2]).min()]) - max([np.array(self._stat_m_data[4]).max(),np.array(self._stat_r_data[4]).max()])
        #ymin=0.9*ymin if ymin>=0 else 1.1*ymin
        #ymax=max([np.array(self._stat_m_data[2]).max(),np.array(self._stat_r_data[2]).max()]) + 3*max([np.array(self._stat_m_data[4]).max(),np.array(self._stat_r_data[4]).max()])
        #ymax=1.1*ymax if ymax>=0 else 0.9*ymax
        ymin=min(self.cfg.mima_ts)
        ymax=max(self.cfg.mima_ts)
        ax.set_ylim(ymin,ymax)
        start=self._ts[0]
        start=start.replace(month=1,day=1)
        stop=self._ts[-1]
        stop=stop.replace(month=12,day=31)+datetime.timedelta(days=1)
        ax.set_xlim(start,stop)
        ax.grid()
        f.savefig(self._get_output_rootname() + '_smean_ts.' + self.output_type)
        plt.close(f.number)
        
        if self.cfg.regionalization:
            unit2=math.ceil(np.sqrt(len(self._regions))) #2
            unit1=math.ceil(len(self._regions)/unit2)
            f = plt.figure(figsize=(30,20)) #(15,40)
            f.suptitle(refname + " and " + modname + ' spatial mean per region', fontsize=14)
            for im in np.arange(0,len(self._regions)):
                ax=f.add_subplot(unit1,unit2,im+1)
                
                M_masked=self._mod_data.copy()
                R_masked=self._ref_data.copy()
                
                M_masked.data.mask=np.logical_or(M_masked.data.mask,self._regions[self._regions.keys()[im]])
                R_masked.data.mask=np.logical_or(R_masked.data.mask,self._regions[self._regions.keys()[im]])
                
                M_pstat=self._p_stat(M_masked,self._ts)
                R_pstat=self._p_stat(R_masked,self._ts)
                
                """ writing portrait statistic for M as csv """
                namerow=np.repeat(self._regions.keys()[im],M_pstat.shape[1])
                M_pstat=np.vstack([M_pstat, namerow])
                R_pstat=np.vstack([R_pstat, namerow])
                onameM = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_regionalized_ts_' + self.cfg.shape + '_' + modname + '_stat.csv'
                onameR = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_regionalized_ts_' + self.cfg.shape + '_' + refname + "_" + modname + '_stat.csv'
                if im == 0:
                    if os.path.exists(onameM):
                        os.remove(onameM)
                    if os.path.exists(onameR):
                        os.remove(onameR)
                    fiM=open(onameM,'w')
                    fiR=open(onameR,'w')
                    try:
                        writer=csv.writer(fiM,quoting=csv.QUOTE_NONNUMERIC)
                        writer.writerow(('date' , 'min' , 'mean' , 'max' , 'sd' , 'cov','count','region')) 
                        writer.writerows(M_pstat.T)
                        writer=csv.writer(fiR,quoting=csv.QUOTE_NONNUMERIC)
                        writer.writerow(('date' , 'min' , 'mean' , 'max' , 'sd' , 'cov','count','region')) 
                        writer.writerows(R_pstat.T)
                    except:
                        print("Could not write to " + onameM + " or " + onameR + "!")
                else:
                    try:
                        writer=csv.writer(fiM,quoting=csv.QUOTE_NONNUMERIC) 
                        writer.writerows(M_pstat.T)
                        writer=csv.writer(fiR,quoting=csv.QUOTE_NONNUMERIC) 
                        writer.writerows(R_pstat.T)
                    except:
                        print("Could not write to " + onameM + " or " + onameR + "!")
                
                if im == len(self._regions)-1:       
                    fiM.close()
                    fiR.close()
                
                ax.plot(self._ts,M_pstat[2], linestyle='-',color="b",label=modname)
                ax.plot(self._ts,R_pstat[2], linestyle='-',color="r",label=refname)
                plt.title(self._regions.keys()[im])
                plt.gcf().autofmt_xdate()
                if not im:
                    plt.legend()
                ax.set_xlabel("")
                ax.set_ylabel(self._vartype + " ["+ self._mod_data.unit +"]")
                ymin=min(self.cfg.mima_mts)
                ymax=max(self.cfg.mima_mts)
                ax.set_ylim(ymin,ymax)
                start=self._ts[0]
                start=start.replace(month=1,day=1)
                stop=self._ts[-1]
                stop=stop.replace(month=12,day=31)+datetime.timedelta(days=1)
                ax.set_xlim(start,stop)
                ax.grid()

            f.savefig(self._get_output_rootname() + '_regionalized_smean_ts.' + self.output_type)
            plt.close(f.number)

    def _global_mean_timeseries(self,name):
        """ calculating mean of TS """
        print('   global mean time series ...')

        if name == self.refname:
            
            #mean of timeseries
            self._gmt_r_data=self._ref_data.copy()
            if self._start_time==self._stop_time and self.var in ["baresoilFrac","grassNcropFrac","shrubNtreeFrac"]:
                self._gmt_r_data.label=self.refname + " " + str(self._start_time)
            else:
                self._gmt_r_data.label=self.refname + ' temporal mean'
            self._gmt_r_data.data=self._ref_data.timmean() 
            
            #timeseries of means
#            self._gmt_r_ts=self._ref_data.data.mean(axis=1).mean(axis=1)[::-1] #global masked mean order is questionable
#            self._gmt_r_ts=[(self._ref_data.data[(self._ref_data.data.shape[0]-s-1),:,:]).mean() for s in np.arange(0,self._ref_data.data.shape[0])] #setwise mean
            
            
        elif name == self.modname:
            #mean of timeseries
            self._gmt_m_data=self._mod_data.copy()
            self._gmt_m_data.label=self.modname + ' temporal mean'
            self._gmt_m_data.data=self._mod_data.timmean()
            
            #timeseries of means
#            self._gmt_m_ts=self._mod_data.data.mean(axis=1).mean(axis=1)[::-1] #global masked mean
#            self._gmt_m_ts=[(self._mod_data.data[(self._mod_data.data.shape[0]-s-1),:,:]).mean() for s in np.arange(0,self._mod_data.data.shape[0])] #setwise mean
            
        else:
            assert False, 'data not expected'

            
    def _plot_global_mean_timeseries(self,name):
        """
        plot global mean timeseries
        """
        #plot temporal agregated map
        Map = SingleMap(self._gmt_r_data if name ==self.refname else self._gmt_m_data, 
                        backend=self.plot_backend, 
                        show_statistic=True,
                        stat_type='mean', 
                        savefile=None, 
                        ax=None,
                        show_unit=True
                        )
        Map.plot(title= name + ' temporal mean', 
                 show_zonal=False, 
                 show_histogram=False,
                 show_timeseries=False, 
                 nclasses=self.plot_nclasses,
                 colorbar_orientation=self.plot_cborientation,
                 show_colorbar=self.plot_cbshow, 
                 cmap=self.cfg.cmap_globmeants, 
                 vmin=min(self.cfg.mima_globmeants),
                 vmax=max(self.cfg.mima_globmeants), 
                 proj_prop=self.cfg.projection, 
                 ctick_prop={'ticks': None, 'labels': None},
                 drawparallels=True,
                 titlefontsize=self.plot_tfont
                 )
        Map.figure.savefig(self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + name + '_gmt.' + self.output_type,
                           dpi=self.plot_dpi)
        plt.close()
        


    def _calc_spatial_correlation(self,X,Y):
        """
        calculate spatial correlation between two 2D Data objects
        """
        assert X.shape == Y.shape, 'ERROR: inconsistent shapes in percentile correlation analysis!'
        assert X.ndim == 2
        #discussions for the correct answer are here: https://github.com/scipy/scipy/issues/3645
        #depending on how you handle missing values especially in intermediate results or degrees of freedom
        
        #slope, intercept, r_value, p_value, std_err = stats.mstats.linregress(X.data.flatten(), Y.data.flatten()) #the original way
        #r_value=np.corrcoef(X.data.flatten(), Y.data.flatten())[0] #the value that is expected (actually the right way. It's not missing values within signals, it's just no value)
        r_value,p_value=stats.pearsonr(X.data.flatten(), Y.data.flatten()) #the expected value plus p-value
        #r_value,p_value=stats.mstats.pearsonr(X.data.flatten(), Y.data.flatten()) #same as original
        return r_value, p_value
        
    def _trend_analysis(self):
        """
        should implement some trend analysis like in

        Dorigo, W., R. deJeu, D. Chung, R. Parinussa, Y. Liu, W. Wagner, and D. Fernandez-Prieto (2012), Evaluating global trends (1988-2010) in harmonized multi-satellite surface soil moisture, Geophys. Res. Lett., 39, L18405, doi:10.1029/2012GL052988.
        """
        
        print('   trend analysis ...')
        
        d_mod=self._mod_data
        d_ref=self._ref_data
        
        if 'anomalytrend' in self.cfg.__dict__.keys():
            if self.cfg.anomalytrend:
                d_mod=self._mod_data.get_deseasonalized_anomaly(base='current')
                d_ref=self._ref_data.get_deseasonalized_anomaly(base='current')
            
        
        #calculating either kendall's tau trend correlation between 2 values pixelwise 
        self._KT_corr,self._KT_pval=self._mapping_tau(d_mod,d_ref)
        
        #temporal trend
        UU_Rr,self._Sr,UU_Ir,self._Pr=self._ref_data.temporal_trend(return_object=True, pthres=1.01)  
        UU_Rm,self._Sm,UU_Im,self._Pm=self._mod_data.temporal_trend(return_object=True, pthres=1.01)
        self._Sr.data=self._Sr.data*365.25
        self._Sr.unit=self._ref_data.unit + " / year"
        self._Sm.data=self._Sm.data*365.25
        self._Sm.unit=self._mod_data.unit + " / year"


    def _mapping_tau(self,dataX,dataY):
        """
        Kendall's Tau correlation mapping        
        """
        
        KT_corr=dataX.get_percentile(0)
        KT_pval=KT_corr.copy()

        shapeX=dataX.shape
        shapeY=dataY.shape
        
        if not shapeX == shapeY:
            assert False, 'The data is misformed!'
            
        dataX=dataX.data.reshape(shapeX[0],shapeX[1]*shapeX[2])    
        dataY=dataY.data.reshape(shapeX[0],shapeX[1]*shapeX[2]) 
        dataXY=np.append(dataX,dataY,axis=0)        
        
        def __my_tau__(v):
            """
            wrapper for kendall's tau along 2 halfs of a vector
            """
            vs=v.shape
            half=vs[0]/2
            return stats.stats.kendalltau(v[np.arange(half)],v[np.arange(half)+half])
        
        Kendall=np.apply_along_axis(__my_tau__,0,dataXY)  
        Kendall.shape=(Kendall.shape[0],shapeX[1],shapeX[2])     
        
        KT_corr.data.data[:]=Kendall[0]
        KT_pval.data.data[:]=Kendall[1]
        
        return KT_corr,KT_pval

         
    def _plot_trend_corr_maps(self, corr, pval):
        """
        plot kendall's tau trend correlations
        """
        f = plt.figure(figsize=(20,6))
        ax1 = f.add_subplot(121)
        ax2 = f.add_subplot(122)
        
        def submap(data,ax,title,vmin,vmax,cmap,ctick={'ticks': None, 'labels': None}):
            Map = SingleMap(data,
                            backend=self.plot_backend,
                            show_statistic=False,
                            savefile=None,
                            ax=ax,
                            show_unit=False)
            Map.plot(title= title,
                     show_zonal=False,
                     show_histogram=False,
                     show_timeseries=False,
                     nclasses=self.plot_nclasses,
                     colorbar_orientation=self.plot_cborientation,
                     show_colorbar=self.plot_cbshow, 
                     cmap=cmap, 
                     vmin=vmin,
                     vmax=vmax, 
                     proj_prop=self.cfg.projection, 
                     ctick_prop=ctick,
                     drawparallels=True,
                     titlefontsize=self.plot_tfont)

        submap(corr, ax=ax1, title="correlation",vmin=-1,vmax=1,cmap='RdBu')
        submap(pval, ax=ax2, title="p-value",vmin=0,vmax=1,cmap='summer',ctick={'ticks': np.arange(0,1.01,0.1), 'labels': np.append(np.arange(0,1,0.1).astype('string'),'> 1.0')})
        
        titlesup="pixelwise Kendall's tau correlation between " + self.refname + " and " + self.modname + " and p-value (" + str(self._start_time.year) + "-" + str(self._stop_time.year) + ")"
        
        oname = self._get_output_rootname() + "_Kendalls_tau" + '.' + self.output_type
        
        if 'anomalytrend' in self.cfg.__dict__.keys():
            if self.cfg.anomalytrend:
                titlesup="pixelwise Kendall's tau correlation between anomalies of " + self.refname + " and " + self.modname + " and p-value (" + str(self._start_time.year) + "-" + str(self._stop_time.year) + ")"
                oname = self._get_output_rootname() + "_Kendalls_tau_anomaly" + '.' + self.output_type
        
        f.suptitle(titlesup)

        if os.path.exists(oname):
            os.remove(oname)
        f.savefig(oname,dpi=self.plot_dpi)

        plt.close(f.number)  # close figure for memory reasons!
        del f
        
    def _plot_trend_maps(self, S, P,name):
        """
        plot trend slopes
        """
        
        if self.cfg.trend_p :
            f = plt.figure(figsize=(20,6))
            ax1 = f.add_subplot(121)
            ax2 = f.add_subplot(122)
    
            def submap(data,ax,title,vmin,vmax,cmap,ctick={'ticks': None, 'labels': None}):
                Map = SingleMap(data,
                                backend=self.plot_backend,
                                show_statistic=True,
                                savefile=None,
                                ax=ax,
                                show_unit=True)
                Map.plot(title= title,
                         show_zonal=False,
                         show_histogram=False,
                         show_timeseries=False,
                         nclasses=self.plot_nclasses,
                         colorbar_orientation=self.plot_cborientation,
                         show_colorbar=self.plot_cbshow, 
                         cmap=cmap, 
                         vmin=vmin,
                         vmax=vmax, 
                         proj_prop=self.cfg.projection, 
                         ctick_prop=ctick,
                         drawparallels=True,
                         titlefontsize=self.plot_tfont)         
            
            #reasonable range from data in the order of tens (should be similar in different datasets)
            if '_Sm' in self.__dict__.keys():
                if '_Sr' in self.__dict__.keys():
                    var= np.nanmin([
                            np.nanmin([
                                np.abs(np.nanmin(self._Sr.data)),np.abs(np.nanmax(self._Sr.data))
                            ]),
                            np.nanmin([
                                np.abs(np.nanmin(self._Sm.data)),np.abs(np.nanmax(self._Sm.data))
                            ])
                        ])
                else:
                    var= np.nanmin([
                            np.abs(np.nanmin(self._Sm.data)),np.abs(np.nanmax(self._Sm.data))
                        ])
            else:
                var= np.nanmin([
                    np.abs(np.nanmin(self._Sr.data)),np.abs(np.nanmax(self._Sr.data))
                ])
            mima=10**np.floor(np.log10(var))
            
            
            submap(S, ax=ax1, title="slope",vmin=-mima,vmax=+mima,cmap='RdBu',ctick={'ticks': np.linspace(-mima,+mima,11), 'labels': np.append(np.insert(np.linspace(-mima,+mima,11).astype('string')[1:10],0,'< ' + str(-mima)),'> ' + str(mima))})
            submap(P, ax=ax2, title="p-value",vmin=0,vmax=1,cmap='summer',ctick={'ticks': np.arange(0,1.01,0.1), 'labels': np.append(np.arange(0,1,0.1).astype('string'),'> 1.0')})
            f.suptitle(name + " pixelwise temporal trend and p-value (" + str(self._start_time.year) + "_" + str(self._stop_time) + ")")
    
            oname = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + name + "_trend+p" + '.' + self.output_type
            if os.path.exists(oname):
                os.remove(oname)
            f.savefig(oname)
    
            plt.close(f.number)  # close figure for memory reasons!
            del f
            
        else:
            f = plt.figure(figsize=(10,6))
            ax1 = f.add_subplot(111)
    
            def submap(data,ax,title,vmin,vmax,cmap,ctick={'ticks': None, 'labels': None}):
                Map = SingleMap(data,
                                backend=self.plot_backend,
                                show_statistic=True,
                                savefile=None,
                                ax=ax,
                                show_unit=True)
                Map.plot(title= title,
                         show_zonal=False,
                         show_histogram=False,
                         show_timeseries=False,
                         nclasses=self.plot_nclasses,
                         colorbar_orientation=self.plot_cborientation,
                         show_colorbar=self.plot_cbshow, 
                         cmap=cmap, 
                         vmin=vmin,
                         vmax=vmax, 
                         proj_prop=self.cfg.projection, 
                         ctick_prop=ctick,
                         drawparallels=True,
                         titlefontsize=self.plot_tfont)         
            
            #reasonable range from data in the order of tens (should be similar in different datasets)
            if '_Sm' in self.__dict__.keys():
                if '_Sr' in self.__dict__.keys():
                    var= np.nanmin([
                            np.nanmin([
                                np.abs(np.nanmin(self._Sr.data)),np.abs(np.nanmax(self._Sr.data))
                            ]),
                            np.nanmin([
                                np.abs(np.nanmin(self._Sm.data)),np.abs(np.nanmax(self._Sm.data))
                            ])
                        ])
                else:
                    var= np.nanmin([
                            np.abs(np.nanmin(self._Sm.data)),np.abs(np.nanmax(self._Sm.data))
                        ])
            else:
                var= np.nanmin([
                    np.abs(np.nanmin(self._Sr.data)),np.abs(np.nanmax(self._Sr.data))
                ])
            mima=10**np.floor(np.log10(var))
            
            M1=S.data.mask
            M2=(P.data>0.05)
            S.data.mask=M1+M2.data
            
            submap(S, ax=ax1, title=name + " pixelwise temporal trend (threshold=0.05, " + str(self._start_time.year) + "-" + str(self._stop_time.year) + ")",vmin=-mima,vmax=+mima,cmap='RdBu',ctick={'ticks': np.linspace(-mima,+mima,11), 'labels': np.append(np.insert(np.linspace(-mima,+mima,11).astype('string')[1:10],0,'< ' + str(-mima)),'> ' + str(mima))})
    
            oname = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + name + "_trend" + '.' + self.output_type
            if os.path.exists(oname):
                os.remove(oname)
            f.savefig(oname)
    
            plt.close(f.number)  # close figure for memory reasons!
            del f
            
        
    def _write_shape_statistics(self,data,diag,name):
        """
        write regionalized statistics
        """   
        oname = self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + 'regionalized_' + self.cfg.shape + '_' + name + '_' + diag + '_stat.csv'
        if os.path.exists(oname):
            os.remove(oname)
        f=open(oname,'w')
        try:
            writer=csv.writer(f,quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(('region' , 'min' , 'mean' , 'max' , 'sd','count')) 
            for R, stat in data.iteritems():
                stat.insert(0,R)
                writer.writerow(stat)
        finally:
            f.close()
            
    def _get_files_in_directory(self, directory, pattern, asstring=True):
        """ returns list and number of files with pattern in directory """
        
        if directory[-1] != os.sep:
            directory += os.sep
            
        L = glob.glob(directory + pattern)
        N = len(L)
        if asstring:
            L = ' '.join(L)
        return L, N
#        
#    def _get_subdirectories(self, directory, asstring=True):
#        """ returns list and number of directories in directory """
#        
#        if directory[-1] != os.sep:
#            directory += os.sep
#            
#        L = glob.glob(directory)
#        N = len(L)
#        if asstring:
#            L = ' '.join(L)
#        return L, N
#        
#    def _aggregate_obs_from_files(self, file_list):
#        """ reads different obs files into one file """
#        cdo=Cdo()
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        try:
#            cdo.cat(input=file_list,output=oname,options = '-f nc4')
#            return oname
#        except OSError:
#            fl=len(file_list)
#            if fl>1:
##                print fl
#                fhalf=file_list[0:int(math.floor(fl/2))]
#                shalf=file_list[int(math.floor(fl/2)):fl]
#                foname=self._aggregate_obs_from_files(fhalf)
#                soname=self._aggregate_obs_from_files(shalf)
#                oname=self._aggregate_obs_from_files([foname,soname])
#                os.remove(foname)
#                os.remove(soname)
#                return oname
#            else:
#                print "package too small"
#        
#    def _aggregate_timestep(self,infile,timestep,remove=True):
#        """ aggregate infile to timestep """
#        """ currenty only monthly """
#        cdo=Cdo()
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        if timestep=="monthly":
#            cdo.monmean(input=infile,output=oname,options='-f nc4 -b F32')
#            if remove:
#                os.remove(infile)
#        else:
#            assert False, "This timestep cannot be handled yet."
#            
#        return oname
#        
#    def _aggregate_specific_years(self,infile,times,remove=True):
#        """ aggregate infile to times with mean and sd"""
#        
#        cdo=Cdo()
#        onameM=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        onameS=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        tmpname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        cdo.selyear(",".join([str(t) for t in times]),input=infile,output=tmpname,options='-f nc4 -b F32')
#        cdo.timselmean(12,input=tmpname,output=onameM,options='-f nc4 -b F32')
#        #cdo.timselstd(12,input=tmpname,output=onameS,options='-f nc4 -b F32')
#        name=cdo.showname(input=onameM)
#        cdo.setname(name[0] + "_std -timselstd,12",input=tmpname,output=onameS,options='-L -f nc4 -b F32')
#        cdo.merge(input=[onameM,onameS],output=oname)
#        if remove:
#            os.remove(infile)
#        os.remove(tmpname)
#        os.remove(onameM)
#        os.remove(onameS)
#            
#        return oname
#        
    def _aggregate_resolution(self,infile,resolution,remove=True): #double in ./reformat_scripts/obs/lib/python/preprocessing_basics.py
        """ currenty only T63, T85 """
        cdo=Cdo()
        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
        if resolution=="T63":
            gridtype = "t63grid"
        elif resolution=="T85":
            gridtype = "t85grid"
        else:
            assert False, "This resolution cannot be handled yet."

        cdo.remapcon(gridtype, input = infile, output = oname, options = '-f nc4 -b F32')
            
        if remove:
            os.remove(infile)   
            
        return oname
#        
#    def _select_variable(self,infile,variablename,remove=False):
#        """ select variables from infile """
#        cdo=Cdo()
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        cdo.selname(variablename,input=infile,output=oname,options='-f nc4 -b F32')
#        if remove:
#            os.remove(infile)
#        return oname
#        
#    def _sum_files(self,infiles,remove=True):
#        """ sum up all infiles """
#        cdo=Cdo()
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        cdo.enssum(input=" ".join(infiles),output=oname,options='-f nc4 -b F32')
#        if remove:
#            for ifi in infiles:
#                os.remove(ifi)
#        return oname
#        
#    def _extract_variables(self,infile,variablenames,newvarname,remove=True):
#        """ select, sum up and rename variable(s) from infile """
#        
#        tmpname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        oname=self._work_dir + os.sep + "temp" + os.sep + tempfile.NamedTemporaryFile().name.split('/')[-1]
#        selfilenames=[]
#        
#        stop=0
#        
#        varnames=list(variablenames)
#        
#        while len(varnames)>stop:
#            
#            v=varnames[0]
#            thisfile=self._select_variable(infile,v)
#            selfilenames.insert(0,thisfile)
#            varnames.remove(v)
#            
#        thisfile=self._sum_files(selfilenames)
#        
#        # adjust variable name and time axis
#        cdo=Cdo()
#        cdo.setname('_'.join(newvarname.split(" ")),input=thisfile,output=tmpname,options='-f nc4 -b F32')
#        cdo.settaxis(infile.split("-")[-2]+"-01-01","00:00",input=tmpname,output=oname,options='-f nc4 -b F32')
#        subprocess.call(['ncatted', '-O', '-a', 'units,' + '_'.join(newvarname.split(" ")) + ',c,c,%', oname])
#        
#        if remove:
#            os.remove(thisfile)
#            os.remove(tmpname)
#        return oname
#        
    def _z_transform(self,data):
        """ global z-transormation """
        
        data_o=data.copy()
        data_o.data=(data_o.data-data_o.timmean())/data_o.timvar()
        
        return data_o
        
    def write_overview(self,plot=True):
        
        if self.overview:
        
            if '_stat_m_data' in self.__dict__.keys() and '_stat_r_data' in self.__dict__.keys():
                
                rootname=self._plot_dir + os.sep + self._vartype.replace(" ","_") + '_' + self.refname + '_' + "all_models"
                onameM =self._vartype.replace(" ","_") + '_regionalized_ts_' + self.cfg.shape + '_' + "*" + '_stat.csv'
                
                M_list_d, M_length = self._get_files_in_directory(self._plot_dir + os.sep,onameM,False)

                onameR =self._vartype.replace(" ","_") + '_regionalized_ts_' + self.cfg.shape + '_' + self.refname + "_" + "*" + '_stat.csv'

                R_list_d, R_length = self._get_files_in_directory(self._plot_dir + os.sep,onameR,False)

                #M_list=filter(lambda x: not(x in R_list_d), M_list_d)
                M_list_d=filter(lambda x: not(x in R_list_d), M_list_d)
                
                M_length=M_length-R_length

                def _file_to_arrays(csvfile):
                    a = {}
                    with open(csvfile) as csvfile:
                        #csvfile=csv.reader(csvfile)
                        for row in csvfile:
                           rowL = row.strip().split(',')
                           if rowL[-1] in a.keys():
                               a[rowL[-1]].append(rowL[:-1])
                           else:
                               a[rowL[-1]] = [rowL[:-1]]
                               
                    del a['"region"']
                    keys=a.keys()
                    a=[np.asarray(a[key]) for key in keys]
                    ts=a[0][::,0]
                    ts=[datetime.datetime.strptime(date, '"%Y-%m-%d"').date() for date in ts]
                    a=[e[::,(2,6)].astype(np.float) for e in a]   
                    
                    return [a,keys,ts]
                    
                #read=_file_to_arrays('/media/bmueller/Work/ESMVAL_res/work/output_plots_directory/sst/sea_surface_temperature_regionalized_ts_Seas_v_ESA-CCI_CMIP5_MPI-ESM-P_historical_r1i1p1_stat.csv')
                
                M_list=[_file_to_arrays(csvfile) for csvfile in M_list_d]
                R_list=[_file_to_arrays(csvfile) for csvfile in R_list_d]

                def _R_arrays_aggregate(modlist):
                    ret_a=[]
                    wsum_a=[]
                    for reg in range(len(modlist[0][0])):
                        wsum=0
                        for li in range(len(modlist)):
                            wsum=wsum+modlist[li][0][reg][::,1]
                        wsum_a.append(wsum)
                        ret_a_e=0
                        for li in range(len(modlist)):
                            ret_a_e=ret_a_e+modlist[li][0][reg][::,0]*modlist[li][0][reg][::,1]/wsum_a[reg]
                        ret_a.append(ret_a_e)
                    return [ret_a,modlist[0][1],modlist[0][2]]
                
                R_list=_R_arrays_aggregate(R_list)
                
                R_list[1]=[reg.replace('"','') for reg in R_list[1]]
                
                R_order=sorted(range(len(R_list[1])), key=lambda k: R_list[1][k])
                
                if self.cfg.regionalization:
                    unit2=2#math.ceil(np.sqrt(len(R_list[1]))) #2
                    unit1=math.ceil(len(R_list[1])/unit2)
                    f = plt.figure(figsize=(20,40))#(10*unit2,4*unit1)) #(15,40)
                    f.suptitle(self.refname + " and " + "models" + ' spatial mean per region', fontsize=14)
                    colors=cm.Set1(np.linspace(0,1,M_length),0.95)
                    #colors=cm.Set1(np.linspace(0,1,M_length))
                    for im in range(len(R_list[1])):
                        ax=f.add_subplot(unit1,unit2,im+1)                       
                        for li in range(M_length):
                            #ax.plot(self._ts,M_list[li][0][R_order[im]][::,0], linestyle='-',color=colors[li],label="_".join(M_list_d[li].split("_")[-5:-1]),linewidth=2.0)
                            ax.plot(self._ts,M_list[li][0][R_order[im]][::,0], linestyle='-',color=colors[li],label=M_list_d[li].split("_")[-2],linewidth=2.0)
                        ax.plot(self._ts,R_list[0][R_order[im]], linestyle='-', alpha=0.95,color="k",label=self.refname,linewidth=2.0)
                        plt.title(R_list[1][R_order[im]])
                        plt.gcf().autofmt_xdate()
                        if [im==(unit1-1)*unit2+1 if len(R_list[1])%unit2 else im==(unit1-1)*unit2][0]:
                            #plt.legend()
                            ax.legend(loc='upper left', bbox_to_anchor=(0, -0.35),ncol=3)
                        ax.set_xlabel("")
                        ax.set_ylabel(self._vartype + " ["+ self._mod_data.unit +"]")
                        ymin=min(self.cfg.mima_mts)
                        ymax=max(self.cfg.mima_mts)
                        ax.set_ylim(ymin,ymax)
                        start=self._ts[0]
                        start=start.replace(month=1,day=1)
                        stop=self._ts[-1]
                        stop=stop.replace(month=12,day=31)+datetime.timedelta(days=1)
                        ax.set_xlim(start,stop)
                        ax.grid()
        
                    f.savefig(rootname + '_regionalized_smean_ts.' + self.output_type)
                    plt.close(f.number)    
