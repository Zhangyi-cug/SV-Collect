import requests
import time
import os
import json
import warnings
import geopandas as gpd

warnings.filterwarnings('ignore')
os.environ['NO_PROXY'] = 'mapsv0.bdimg.com'


class scrap_baidu_v2:
    def __init__(self, url, save_path, shp, workSpace, header):
        self.url = url
        self.save_path = save_path
        self.shp = shp
        self.workSpace = workSpace
        self.header = header

    def get_UP(self):
        data = gpd.read_file(self.shp)["DIREC"]
        result = [90 - item for item in data]
        return result

    def get_DOWN(self):
        data = gpd.read_file(self.shp)["DIREC"]
        result = [270 - item for item in data]
        return result

    def get_LEFT(self):
        data = gpd.read_file(self.shp)["DIREC"]
        result = []
        for item in data:
            if item < 0:
                result.append(abs(item))
            else:
                result.append(360 - item)
        return result

    def get_RIGHT(self):
        data = gpd.read_file(self.shp)["DIREC"]
        result = [180 - item for item in data]
        return result

    def get_location(self):
        xs = gpd.read_file(self.shp)["F84X"]
        ys = gpd.read_file(self.shp)["F84Y"]

        count = 0
        point = []
        for item in zip(xs, ys):
            flag = True
            x, y = item
            count = count + 1
            while flag:
                try:
                    url = 'http://api.map.baidu.com/geoconv/v1/?coords={},{}&from=1&to=6&ak=5YliFO5KYXvlkCaaIht8E2Ket5XosUgn'.format(
                        x, y)
                    r = requests.get(url, headers=self.header, verify=False)
                    html = r.text
                    html_f = json.loads(html)
                    lng, lat = html_f['result'][0]['x'], html_f['result'][0]['y']
                    location = (lng, lat)
                    point.append(location)
                    flag = False
                except:
                    print('The request is too frequent. Please wait for 5 seconds.')
                    time.sleep(5)
                    flag = True
            print(count)
        return point

    def get_FID(self):
        data = gpd.read_file(self.shp)["pointID"]
        return data

    def load_web(self, loc):
        url_f = self.url.format(loc[0], loc[1])
        r = requests.get(url_f, verify=False, headers=self.header)
        if r.status_code == 200:
            print('Request succeeded')
            return r
        else:
            print('Request failed')

    def parse_web(self, loc):
        r = self.load_web(loc)
        html = r.text
        id = None
        try:
            json_f = json.loads(html)
            id = json_f['content']['id']
            return id
        except:
            print('There is no street view available at this location.')
            return id

    def save_data(self, loc, point_id, heading, dic=None):
        id_ = self.parse_web(loc)
        flag = True
        if id_ != None:
            url_re = r'https://mapsv0.bdimg.com/?qt=sdata&sid={}&pc=1'.format(id_)
            if not os.path.exists(self.save_path):
                os.mkdir(self.save_path)
            while flag:
                try:
                    r = requests.get(url_re, verify=False, headers=self.header)
                    html = r.text
                    json_f = json.loads(html)
                    IDs = [i_list['ID'] for i_list in json_f['content'][0]['TimeLine']]
                    Years = [i_list['Year'] for i_list in json_f['content'][0]['TimeLine']]
                    if len(Years) >= 2:
                        for id, year in zip(IDs, Years):
                            print('pontid:{}'.format(point_id))
                            time.sleep(1)
                            filename = self.save_path + '/' + str(year) + '_' + str(int(point_id)) + '_' + dic + '.jpg'
                            f = open(filename, 'wb')
                            # Adjust the focus, size and pitch.
                            url = 'https://mapsv0.bdimg.com/?qt=pr3d&fovy=85&quality=100&panoid={}&heading={}&pitch=0&width=800&height=400'.format(
                                id, heading)
                            r = requests.get(url, verify=False, headers=self.header)
                            pic = r.content
                            f.write(pic)
                            f.flush()
                            f.close()
                    flag = False
                except:
                    print('The request is too frequent. Please wait for 5 seconds.')
                    time.sleep(5)
                    flag = True


if __name__ == '__main__':
    workSpace = r'samples'
    shp = r'samples\sampling_points.shp'
    header = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0'}
    save_path = r'samples\SVs'

    url = r'https://mapsv0.bdimg.com/?qt=qsdata&x={}&y={}'
    sb = scrap_baidu_v2(url=url, save_path=save_path, shp=shp, workSpace=workSpace, header=header)
    locs = sb.get_location()
    len(locs)

    pointIDs = sb.get_FID()
    Fs = sb.get_UP()
    Ls = sb.get_LEFT()
    Bs = sb.get_DOWN()
    Rs = sb.get_RIGHT()
    for loc, pointID, F, L, B, R in zip(locs, pointIDs, Fs, Ls, Bs, Rs):
        sb.save_data(loc, pointID, F, 'F')
        sb.save_data(loc, pointID, L, 'L')
        sb.save_data(loc, pointID, B, 'B')
        sb.save_data(loc, pointID, R, 'R')

