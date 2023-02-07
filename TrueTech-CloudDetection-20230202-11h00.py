#!/usr/bin/env python
# coding: utf-8

# -------------------
# # Initialize

# In[1]:

import os
import json
os.system('CLS')

import ee
import geemap
import geopandas as gpd

import folium

print('\n---------------------------------------')
print('TrueTech - Sentinel2 MSI cloud detection')

# In[2]:



#----------------------------------
# Trigger the authentication flow.
#     ee.Authenticate()

#----------------------------------
# Khởi tạo thư viện.
ee.Initialize()


# 

# In[3]:


from dateutil import parser

# start_date = parser.parse(input("Enter start date: "))
# end_date = parser.parse(input("Enter end date: "))

# print(start_date)


# -------------------------------
# # Function

# In[4]:


def get_shape_file(path):
    my_shape = gpd.read_file(path)
    geo_json = my_shape.to_json()

    my_shape = ee.FeatureCollection(json.loads(geo_json))
    return my_shape
    #     .filterBounds(my_shape.geometry())
    


# In[5]:


def get_s2_sr_cld_col(my_shape, start_date, end_date):
    # Import and filter S2 SR.
    s2_sr_col = (ee.ImageCollection('COPERNICUS/S2_SR')
        .filterBounds(my_shape)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', CLOUD_FILTER)))
#         .filterBounds(aoi)
        

    # Import and filter s2cloudless.
    s2_cloudless_col = (ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY')
        .filterBounds(my_shape)
        .filterDate(start_date, end_date))

    # Join the filtered s2cloudless collection to the SR collection by the 'system:index' property.
    return ee.ImageCollection(ee.Join.saveFirst('s2cloudless').apply(**{
        'primary': s2_sr_col,
        'secondary': s2_cloudless_col,
        'condition': ee.Filter.equals(**{
            'leftField': 'system:index',
            'rightField': 'system:index'
        })
    }))


# In[6]:


def add_cloud_bands(img):
    # Get s2cloudless image, subset the probability band.
    cld_prb = ee.Image(img.get('s2cloudless')).select('probability')

    # Condition s2cloudless by the probability threshold value.
    is_cloud = cld_prb.gt(CLD_PRB_THRESH).rename('clouds')

    # Add the cloud probability layer and cloud mask as image bands.
    return img.addBands(ee.Image([cld_prb, is_cloud]))


# In[7]:


def add_shadow_bands(img):
    # Identify water pixels from the SCL band.
    not_water = img.select('SCL').neq(6)

    # Identify dark NIR pixels that are not water (potential cloud shadow pixels).
    SR_BAND_SCALE = 1e4
    dark_pixels = img.select('B8').lt(NIR_DRK_THRESH*SR_BAND_SCALE).multiply(not_water).rename('dark_pixels')

    # Determine the direction to project cloud shadow from clouds (assumes UTM projection).
    shadow_azimuth = ee.Number(90).subtract(ee.Number(img.get('MEAN_SOLAR_AZIMUTH_ANGLE')));

    # Project shadows from clouds for the distance specified by the CLD_PRJ_DIST input.
    cld_proj = (img.select('clouds').directionalDistanceTransform(shadow_azimuth, CLD_PRJ_DIST*10)
        .reproject(**{'crs': img.select(0).projection(), 'scale': 100})
        .select('distance')
        .mask()
        .rename('cloud_transform'))

    # Identify the intersection of dark pixels with cloud shadow projection.
    shadows = cld_proj.multiply(dark_pixels).rename('shadows')

    # Add dark pixels, cloud projection, and identified shadows as image bands.
    return img.addBands(ee.Image([dark_pixels, cld_proj, shadows]))


# In[8]:


def add_cld_shdw_mask(img):
    # Add cloud component bands.
    img_cloud = add_cloud_bands(img)

    # Add cloud shadow component bands.
    img_cloud_shadow = add_shadow_bands(img_cloud)

    # Combine cloud and shadow mask, set cloud and shadow as value 1, else 0.
    is_cld_shdw = img_cloud_shadow.select('clouds').add(img_cloud_shadow.select('shadows')).gt(0)

    # Remove small cloud-shadow patches and dilate remaining pixels by BUFFER input.
    # 20 m scale is for speed, and assumes clouds don't require 10 m precision.
    is_cld_shdw = (is_cld_shdw.focalMin(2).focalMax(BUFFER*2/20)
        .reproject(**{'crs': img.select([0]).projection(), 'scale': 20})
        .rename('cloudmask'))

    # Add the final cloud-shadow mask to the image.
    return img_cloud_shadow.addBands(is_cld_shdw)


# In[9]:


# Import the folium library.

# Define a method for displaying Earth Engine image tiles to a folium map.
def add_ee_layer(self, ee_image_object, vis_params, name, show=True, opacity=1, min_zoom=0):
    map_id_dict = ee.Image(ee_image_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Map Data &copy; <a href="https://earthengine.google.com/">Google Earth Engine</a>',
        name=name,
        show=show,
        opacity=opacity,
        min_zoom=min_zoom,
        overlay=True,
        control=True
        ).add_to(self)

# Add the Earth Engine layer method to folium.
folium.Map.add_ee_layer = add_ee_layer


# In[10]:


#----------------------------------------------------------------------
def CreateMap(bound):
    # Create a folium map object.
    center = bound.geometry()                    .centroid()                    .coordinates()                    .reverse()                    .getInfo()

    Map = folium.Map(location=center, zoom_start=zoom_start)
    return Map
    
#----------------------------------------------------------------------
def display_cloud_layers(col):
    # Mosaic the image collection.
    img = col#.mosaic()
    cloudmask = img.select('cloudmask').selfMask()

    # Create a folium map object.
    Map = CreateMap(my_shape)

    # Add layers to the folium map.
    Map.add_ee_layer(img,
                   {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 2500, 'gamma': 1.1},
                   'S2 image', True, 1, 9)
    
    Map.add_ee_layer(cloudmask, {'palette': 'yellow'},
                   'cloudmask', True, 0.5, 9)

    # Add a layer control panel to the map.
    Map.add_child(folium.LayerControl())

    # Display the map.
    display(Map)


# -------------------
# # Parameter

# In[21]:

# --------------------------------------------------------------------------------------------------------
print('Enter parameter!\n')
# --------------------------------------------------------------------------------------------------------
path_shapefile = input('Enter AOI:')
if path_shapefile == '':
    path_shapefile = 'D:\\Learn\\shapefile\\DaNang\\DaNang_rec\\DangNang_rec.geojson'
print('\t=>', path_shapefile)
# Load shapefile
my_shape = get_shape_file(path_shapefile)
AOI = my_shape.geometry().centroid()

# --------------------------------------------------------------------------------------------------------
START_DATE = input("Enter StartDate: ") # 
if START_DATE == '':
    START_DATE = '2019-03-01'
print('\t=>', START_DATE)

# --------------------------------------------------------------------------------------------------------
END_DATE = input("Enter EndDate: ") # 
if END_DATE == '':
    END_DATE = '2019-03-10'
print('\t=>', END_DATE)


# In[12]:



#----------------------------------

# Phần trăm che phủ đám mây hình ảnh tối đa được phép trong bộ sưu tập hình ảnh
CLOUD_FILTER = input('Maximum image cloud cover percent (%) allowed in image collection:')
if CLOUD_FILTER == '':
    CLOUD_FILTER = 10
print('\t=>', CLOUD_FILTER, '%')

# Xác suất đám mây (%); các giá trị lớn hơn được coi là đám mây
CLD_PRB_THRESH = input('Cloud probability (%); values greater than are considered cloud: ')
if CLD_PRB_THRESH == '':
    CLD_PRB_THRESH = 65
print('\t=>', CLD_PRB_THRESH, '%')

# phản xạ cận hồng ngoại; các giá trị nhỏ hơn được coi là bóng mây tiềm ẩn
NIR_DRK_THRESH = input('Near-infrared reflectance; values less than are considered potential cloud shadow:')
if NIR_DRK_THRESH == '':
    NIR_DRK_THRESH = 0.15
print('\t=>', NIR_DRK_THRESH)

# Khoảng cách tối đa (km) để tìm bóng mây từ rìa mây
CLD_PRJ_DIST = input('Maximum distance (km) to search for cloud shadows from cloud edges:')
if CLD_PRJ_DIST == '':
    CLD_PRJ_DIST = 0.8
print('\t=>', CLD_PRJ_DIST, 'km')

# Khoảng cách (m) để mở rộng cạnh của các đối tượng được xác định bằng đám mây
BUFFER = input('Distance (m) to dilate the edge of cloud-identified objects:')
if BUFFER == '':
    BUFFER = 50
print('\t=>', BUFFER, 'm')

# Hệ số zoom ban đầu, dùng cho biểu diễn kết quả
zoom_start = 10.5

BANDMAP = ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12',
           'cloudmask']
#             'AOT', 'WVP', 'SCL',
#            'TCI_R', 'TCI_G', 'TCI_B',
#            'MSK_CLDPRB', 


# # Main

# In[13]:


def main (START_DATE, END_DATE):

    #----------------------------------
    # Nội dung chính
    try:
        # Download dữ liệu
        s2_sr_cld_col_eval = get_s2_sr_cld_col(AOI, START_DATE, END_DATE)
        # Check số lượng ảnh hợp lệ
        NumImage = s2_sr_cld_col_eval.size().getInfo()
        if NumImage == 0: # không có ảnh nào thì return
            print ('no image => break!')
            return 
        else: # có ảnh thì tính mây
            # print(" number of image: ", NumImage)
            # hàm tính mây
            s2_sr_cld_col_eval_disp = s2_sr_cld_col_eval.map(add_cld_shdw_mask)
    except:
        print ('something wrong => break!')
        return

    #----------------------------------
    # return 
    output_collection = s2_sr_cld_col_eval_disp .select(BANDMAP)                                                .map(lambda image: image.clip(my_shape))
    
    
    return output_collection
    # ...


if __name__ == "__main__":

    # main
    print('\n---------------------------------------')
    print('processing...')
    
    output_collection = main(START_DATE, END_DATE)

    print('\t=> done processing!')
    
    #----------------------------------


# In[14]:




# In[22]:


while True:
    print('\n---------------------------------------')
    print('Export collection!')
    try:
        len_col = len(output_collection.getInfo()['features'])
        print('Number of image:', len_col)

    except:
        print("Don't have any image valid!")
        break

    check_download = input("Enter 'y' to download the collection:")

    if check_download == 'y':
        # --------------------------------------------------------------------------------------------------------
        # set output folder
        output_foler = input('Enter OutputFolder:')
        if output_foler == '':
            output_foler = 'E:\\TrueTech\\MAE\\python\\output\\'
        out_dir = os.path.join(output_foler)
        # output_filename = os.path.join(out_dir, 'output.tif')
        print('\t=>', output_foler)

        # --------------------------------------------------------------------------------------------------------
        # download
        print('\n---')
        print('Downloading...')
        try:
            geemap.download_ee_image_collection(output_collection,
                                                    out_dir, 
                                                    region=my_shape.geometry(),
                                                    scale=10
                                                   )
            print('\t=> download done!')
            break
        except:
            print('\n---')
            print('\t=> download error!')
            break
    else:
        print('\t=> bye!')
        break

