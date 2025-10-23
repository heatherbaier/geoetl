import os
import json
import geopandas as gpd
import requests
import rioxarray as riox
from shapely.geometry import box
from shapely.ops import unary_union
from tqdm import tqdm
from rioxarray.merge import merge_arrays
import urllib.request

class GEESource:
    def __init__(self, api_key, out_root, mosaic_name):
        """
        In here, set up all of the variables you'll need and do the GEE Initlialization
        """
        # ee.Initialize()
        self.ic = mosaic_name
        pass # remove this when you start coding!

    def find_local_tiles(self, geom, quads_dir):
        """
        This should find any images from the mosaic that 
        """
#         cur_shp = pygee.convert_to_ee_feature(geom)

#         if im:
#             m = ee.Image(self.ic)
#             if bands is not None:
#                 m = m.select(bands)
#         elif not im:
#             if dates is not None:
#                 imagery = ee.ImageCollection(self.ic).filterDate(dates[0], dates[1]).filterBounds(cur_shp)
#             else:
#                 imagery = ee.ImageCollection(self.ic).filterBounds(cur_shp)
#             if v:
#                 print(shapeID, " has ", imagery.size().getInfo(), " images available between ", " and ".join(dates))
#             if cloud_free:
#                 m = ee.Algorithms.Landsat.simpleComposite(imagery).select(bands)
#             elif not cloud_free:
#                 m = imagery.select(bands).median()           
    #return m



        

    def download_tiles_for_geometry(self, geom, quads_dir):
        """
        This should be skipped in GEE I believe 
        (and will be sicne we are returning True from has_all_tiles for now)
        """
        pass
        

    def clip_to_geometry(self, geom, out_path, quads_dir):
        """
        Clip the imagery collection from find_local_tiles to the shape of the polygon
        Then,s ave the image as a file.
        """
        # cur_shp = pygee.convert_to_ee_feature(geom)
        # m = m.clip(cur_shp)
        
        # region = ee.Geometry.Rectangle(list(geom.bounds))
        
        # if dates is not None:
        #     fname = cur_directory + "/" + shapeID + "_" + "_".join(dates) + ".zip"
        #     lname = shapeID + "_" + "_".join(dates)
        # else:
        #     fname = cur_directory + "/" + shapeID + ".zip"
        #     lname = shapeID
            
        # # Get the URL download link
        # link = m.getDownloadURL({
        #         'name': lname,
        #         'crs': 'EPSG:4326',
        #         'fileFormat': 'GeoTIFF',
        #         'region': region,
        #         'scale': scale,
        #         'maxPixels': 1e9
        # })
        
        # r = requests.get(link, allow_redirects = True)
        # open(out_path, 'wb').write(r.content)
        pass # remove when you start coding!
        


    def has_all_tiles(self, geom, out_path):
        """
        This should be skipped in GEE I believe.
        But needs to return something satisfactory to the pipleline loop for the code to work...
        Return True should be sufficient for now but should think through more later.
        """
        return True