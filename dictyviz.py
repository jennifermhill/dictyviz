# Dicty data functions for ome-zarr datasets

import copy
import math
import os

import zarr
import cv2
import cmapy
import numpy as np
from tqdm import tqdm

# define global variables
IMAGING_FREQ = 10

def createRootStore(zarrFile):
    nestedStore = zarr.NestedDirectoryStore(zarrFile, dimension_separator='/')
    root = zarr.group(store=nestedStore, overwrite=False)

def createZarrGroup(root, groupName):

    if groupName in root:
        group = root[groupName]
    else:
        group = root.create_group(groupName)
    return group

class channel:
    def __init__(self, name, nChannel, scaleMax, adjMin=0):
        self.name = name
        self.nChannel = nChannel
        self.scaleMax = scaleMax
        self.adjMin = adjMin

def calcMaxProjections(root, res_lvl=0):

    # define resolution level
    resArray = root['0'][str(res_lvl)]

    # get dataset dimensions
    lenT, lenCh, lenZ, lenY, lenX = resArray.shape
    
    analysisGroup = root['analysis']

    # create max projections group
    maxProjectionsGroup = createZarrGroup(analysisGroup, 'max_projections')

    # create zarr arrays for each max projection 
    maxZ = maxProjectionsGroup.zeros('maxz',shape=(lenT,lenCh,2,lenY,lenX),chunks=(1,lenCh,2,lenY,lenX))
    maxX = maxProjectionsGroup.zeros('maxx',shape=(lenT,lenCh,lenZ,lenY),chunks=(1,lenCh,lenZ,lenY))
    maxY = maxProjectionsGroup.zeros('maxy',shape=(lenT,lenCh,lenZ,lenX),chunks=(1,lenCh,lenZ,lenX))

    # iterate through each timepoint and compute max projections
    for i in tqdm(range(lenT)):
        for j in range(lenCh):
            frame = resArray[i, j, :, :, :]
            maxZ[i,j] = [np.max(frame,axis=0), np.argmax(frame,axis=0)]
            maxX[i,j] = np.max(frame,axis=2)
            maxY[i,j] = np.max(frame,axis=1)


def calcSlicedMaxProjections(root, res_lvl=0):
    # define resolution level
    resArray = root['0'][str(res_lvl)]

    # get dataset dimensions
    lenT, lenCh, lenZ, lenY, lenX = resArray.shape

    analysisGroup = root['analysis']

    # create max projections group
    slicedMaxProjectionsGroup = createZarrGroup(analysisGroup, 'sliced_max_projections')

    # set number of slices
    sliceDepth = 83 # 83px*2.41um/px = 200 um
    nSlicesX = math.ceil(lenX/sliceDepth)
    nSlicesY = math.ceil(lenY/sliceDepth)

    # create zarr arrays for each max projection
    slicedMaxX = slicedMaxProjectionsGroup.zeros('sliced_maxx',shape=(lenT,lenCh,nSlicesX,lenZ,lenY),chunks=(1,1,2,lenZ,lenY))
    slicedMaxY = slicedMaxProjectionsGroup.zeros('sliced_maxy',shape=(lenT,lenCh,nSlicesY,lenZ,lenX),chunks=(1,1,2,lenZ,lenX))

    for i in tqdm(range(lenT)):
        for j in range(lenCh):
            for k in range(nSlicesX):
                rangeX = [k*sliceDepth, (k+1)*sliceDepth]
                frame = resArray[i,j,:,:,rangeX[0]:rangeX[1]]
                slicedMaxX[i,j,k] = np.max(frame,axis=2)

            for k in range(nSlicesY):
                rangeY = [k*sliceDepth, (k+1)*sliceDepth]
                frame = resArray[i,j,:,rangeY[0]:rangeY[1],:]
                slicedMaxY[i,j,k] = np.max(frame,axis=1)

def generateUniqueFilename(filename, ext):
    i = 1
    while os.path.exists(filename + ext):
        if i == 1:
            filename = filename +'_1'
        else:
            filename = filename[:-1] + str(i)
        i += 1
    return filename + ext

# replace with an adjustable auto contrast of some sort
def calcScaleMax(root):
    maxZ = root['analysis']['max_projections']['maxz']
    scaleMax = np.max(maxZ)
    return scaleMax

def getProjectionDimensions(maxX, maxY):
    # return the dimensions of the max projections
    lenT = maxX.shape[0]
    lenZ = maxX.shape[-2]
    lenY = maxX.shape[-1]
    lenX = maxY.shape[-1]
    return lenT, lenZ, lenY, lenX

def adjustContrast(im, adjMax, adjMin):
    im = np.clip(im,adjMin,adjMax)
    backSub = im - adjMin
    backSub[np.where(backSub<0)] = 0
    scaledIm = np.divide(backSub,adjMax-adjMin)
    contrastedIm = np.multiply(scaledIm,255).astype('uint8')
    return(contrastedIm)

class scaleBar:
    def __init__(self, posY, posX, height, length, text, textOffset):
        self.posY = posY
        self.posX = posX
        self.height = height
        self.length = length
        self.text = text
        self.textOffset = textOffset

    def _addScaleBar(self, frame):
        frame[self.posY:self.posY+self.height, self.posX:self.posX+self.length,:] = 255
        cv2.putText(frame, self.text, (self.posX+self.textOffset, self.posY-10), #self.posY-30
                    cv2.FONT_HERSHEY_SIMPLEX, 1, [255,255,255], 3, cv2.LINE_AA) #3, 6

    def _addScaleBarZ(self, frame):
        frame[self.posY:self.posY+self.height, self.posX:self.posX+self.length,:] = 255
        cv2.putText(frame, self.text, (self.posX, self.posY-10), #self.posY-50
                    cv2.FONT_HERSHEY_SIMPLEX, 0.1, [255,255,255], 1, cv2.LINE_AA)

def makeOrthoMaxVideo(root, channel, ext='.avi'):

    filename = generateUniqueFilename(channel.name + '_orthomax', ext)
    nChannel = channel.nChannel
    adjMax = channel.scaleMax
    adjMin = channel.adjMin

    maxZ = root['analysis']['max_projections']['maxz']
    maxY = root['analysis']['max_projections']['maxy']
    maxX = root['analysis']['max_projections']['maxx']
    
    lenT, lenZ, lenY, lenX = getProjectionDimensions(maxX, maxY)
    
    gap = 20

    movieWidth = lenX + lenZ + gap
    movieHeight = lenY + lenZ + gap

    vid = cv2.VideoWriter(filename,cv2.VideoWriter_fourcc(*'MJPG'),10,(movieWidth,movieHeight),1)

    for i in tqdm(range(lenT)):

        # initialize frame 
        im = np.zeros([movieHeight,movieWidth])

        # copy max projections 
        im[0:lenZ,0:lenX] = copy.copy(np.flip(maxY[i,nChannel],axis=0))
        im[(lenZ+gap):movieHeight,0:lenX] = copy.copy(maxZ[i,nChannel,0])
        im[(lenZ+gap):movieHeight,(lenX+gap):movieWidth] = copy.copy(np.transpose(maxX[i,nChannel]))
        
        contrastedIm = adjustContrast(im, adjMax, adjMin)

        # invert if rock channel
        if channel.name == 'rocks':
            contrastedIm = 255 - contrastedIm

        frame = cv2.applyColorMap(contrastedIm,cmapy.cmap('viridis'))

        frame[np.where(im==0)] = [0,0,0]
        
        # time stamp
        t = f'{i*IMAGING_FREQ // 60:02d}' + ':' + f'{i*IMAGING_FREQ % 60:02d}'
        #cv2.putText(frame,t,(25,lenZ+gap+150),cv2.FONT_HERSHEY_SIMPLEX,6,[255,255,255],10,cv2.LINE_AA)
        cv2.putText(frame,t,(15,lenZ+gap+30),cv2.FONT_HERSHEY_SIMPLEX,1,[255,255,255],3,cv2.LINE_AA)

        # add scale bars
        scaleBarXY = scaleBar(
            posY = movieHeight - 20, #76
            posX = lenX - 50, #468
            height = 10, #30
            length = 42, #416
            text = '100 um', #1 mm
            textOffset = 0, #50
        )
        scaleBarXY._addScaleBar(frame)

        scaleBarXZ = scaleBar(
            posY = lenZ,
            posX = lenX + gap,
            height = 10, #30
            length = lenZ,
            text = str(lenZ * 2) + ' um',
            textOffset = 5, #50
        )
        scaleBarXZ._addScaleBarZ(frame)

        # write frame 
        vid.write(frame)

    vid.release()
    cv2.destroyAllWindows()

def makeSlicedOrthoMaxVideos(root, channel, ext='.avi'):

    filenames = [generateUniqueFilename(channel.name + '_X_sliced_orthomax', ext),
                 generateUniqueFilename(channel.name + '_Y_sliced_orthomax', ext)]
    nChannel = channel.nChannel
    adjMax = channel.scaleMax
    adjMin = channel.adjMin
        
    slicedMaxes = [root['analysis']['sliced_max_projections']['sliced_maxx'], root['analysis']['sliced_max_projections']['sliced_maxy']]

    lenT, lenZ, _, _ = getProjectionDimensions(slicedMaxes[0], slicedMaxes[1])

    gap = 20

    for filename, slicedMax in zip(filenames, slicedMaxes):
        
        nSlices = slicedMax.shape[2]

        movieWidth = slicedMax.shape[-1]
        movieHeight = (lenZ * nSlices) + (gap * (nSlices-1))

        vid = cv2.VideoWriter(filename,cv2.VideoWriter_fourcc(*'MJPG'),10,(movieWidth,movieHeight),1)

        for i in tqdm(range(lenT)):

            # initialize frame
            im = np.zeros([movieHeight,movieWidth])

            # copy max projections 
            for j in range(nSlices):
                im[(lenZ*j+gap*j):(lenZ*(j+1)+gap*j),:] = copy.copy(np.flip(slicedMax[i,nChannel,j], axis=0))

            # adjust contrast
            contrastedIm = adjustContrast(im, adjMax, adjMin)

            # invert if rock channel
            if channel.name == 'rocks':
                contrastedIm = 255 - contrastedIm

            frame = cv2.applyColorMap(contrastedIm,cmapy.cmap('viridis'))

            frame[np.where(im==0)] = [0,0,0]

            # add time stamp
            t = f'{i*IMAGING_FREQ // 60:02d}' + ':' + f'{i*IMAGING_FREQ % 60:02d}'
            cv2.putText(frame,t,(25,150),cv2.FONT_HERSHEY_SIMPLEX,6,[255,255,255],10,cv2.LINE_AA)

            # add scale bar
            scaleBarXY = scaleBar(
                posY = movieHeight - 76,
                posX = movieWidth - 468,
                height = 30,
                length = 416,
                text = '1 mm',
                textOffset = 50,
            )
            scaleBarXY._addScaleBar(frame)

            # write frame
            vid.write(frame)

        vid.release()
        cv2.destroyAllWindows()

def makeCompOrthoMaxVideo(root, channels, ext='.avi'):

    filename = generateUniqueFilename('comp_orthomax', ext)

    # set channel values
    for channel in channels:
        if channel.name == 'cells':
            nChannelCells = channel.nChannel
            scaleMaxCells = channel.scaleMax
            adjMinCells = channel.adjMin
        else:
            nChannelRocks = channel.nChannel
            scaleMaxRocks = channel.scaleMax
            adjMinRocks = channel.adjMin

    maxZ = root['analysis']['max_projections']['maxz']
    maxY = root['analysis']['max_projections']['maxy']
    maxX = root['analysis']['max_projections']['maxx']
    
    lenT, lenZ, lenY, lenX = getProjectionDimensions(maxX, maxY)

    gap = 20

    movieWidth = lenX + lenZ + gap
    movieHeight = lenY + lenZ + gap

    vid = cv2.VideoWriter(filename,cv2.VideoWriter_fourcc(*'MJPG'),10,(movieWidth,movieHeight),1)

    for i in tqdm(range(lenT)):
        
        imCells = np.zeros([movieHeight,movieWidth])
        imRocks = np.zeros([movieHeight,movieWidth])

        # copy max projections 
        imCells[0:lenZ,0:lenX] = copy.copy(np.flip(maxY[i,nChannelCells],axis=0))
        imCells[(lenZ+gap):movieHeight,0:lenX] = copy.copy(maxZ[i,nChannelCells,0])
        imCells[(lenZ+gap):movieHeight,(lenX+gap):movieWidth] = copy.copy(np.transpose(maxX[i,nChannelCells]))

        imRocks[0:lenZ,0:lenX] = copy.copy(np.flip(maxY[i,nChannelRocks],axis=0))
        imRocks[(lenZ+gap):movieHeight,0:lenX] = copy.copy(maxZ[i,nChannelRocks,0])
        imRocks[(lenZ+gap):movieHeight,(lenX+gap):movieWidth] = copy.copy(np.transpose(maxX[i,nChannelRocks]))
        
        contrastedImCells = adjustContrast(imCells, scaleMaxCells, adjMinCells)
        contrastedImRocks = adjustContrast(imRocks, scaleMaxRocks, adjMinRocks)

        # invert rock channel
        contrastedImRocks = 255 - contrastedImRocks

        frame = cv2.merge((contrastedImCells,contrastedImRocks,contrastedImCells))

        frame[np.where(contrastedImCells==0)] = [0,0,0]
        
        # time stamp
        t = f'{i*IMAGING_FREQ // 60:02d}' + ':' + f'{i*IMAGING_FREQ % 60:02d}'
        #cv2.putText(frame,t,(25,lenZ+gap+150),cv2.FONT_HERSHEY_SIMPLEX,6,[255,255,255],10,cv2.LINE_AA)
        cv2.putText(frame,t,(15,lenZ+gap+30),cv2.FONT_HERSHEY_SIMPLEX,1,[255,255,255],3,cv2.LINE_AA)

        # add scale bars
        scaleBarXY = scaleBar(
            posY = movieHeight - 20, #76
            posX = lenX - 50, #468
            height = 10, #30
            length = 42, #416
            text = '100 um', #1 mm
            textOffset = 0, #50
        )
        scaleBarXY._addScaleBar(frame)

        scaleBarXZ = scaleBar(
            posY = lenZ,
            posX = lenX + gap,
            height = 10, #30
            length = lenZ,
            text = str(lenZ * 2) + ' um',
            textOffset = 5, #50
        )
        scaleBarXZ._addScaleBarZ(frame)

        # write frame 
        vid.write(frame)

    vid.release()
    cv2.destroyAllWindows()

def generateZDepthColormap(lenZ, cmap):
    #generates a colormap based on z depth, red is the highest z depth, blue is the lowest
    zDepthColormap = [None]*lenZ
    for slice in range(0,lenZ):
        zDepthGrayVal = round((slice/lenZ)*255)
        zDepthColormap[slice] = cmapy.color(cmap, zDepthGrayVal)
    return zDepthColormap

def invertAndScale(channel, im):
    # invert if rock channel
    if channel == 'rocks':
        im = 255 - im
    scaledIm = np.divide(im,255)
    scaledImGrayscale = cv2.merge([scaledIm, scaledIm, scaledIm])
    return scaledImGrayscale

def makeZDepthOrthoMaxVideo(root, channel, cmap, ext='.avi'):

    filename = generateUniqueFilename(channel.name + '_zdepth_orthomax', ext)
    nChannel = channel.nChannel
    adjMax = channel.scaleMax
    adjMin = channel.adjMin

    maxZ = root['analysis']['max_projections']['maxz']
    maxY = root['analysis']['max_projections']['maxy']
    maxX = root['analysis']['max_projections']['maxx']
    
    lenT, lenZ, lenY, lenX = getProjectionDimensions(maxX, maxY)

    zDepthColormap = generateZDepthColormap(lenZ, cmap)
    
    gap = 20

    movieWidth = lenX + lenZ + gap
    movieHeight = lenY + lenZ + gap

    vid = cv2.VideoWriter(filename,cv2.VideoWriter_fourcc(*'MJPG'),10,(movieWidth,movieHeight),1)

    for i in tqdm(range(lenT)):

        # generate a scaled image for the XY projection
        imXY = copy.copy(maxZ[i,nChannel,0])
        contrastedImXY = adjustContrast(imXY, adjMax, adjMin)
        scaledImGrayscaleXY = invertAndScale(channel.name, contrastedImXY)

        # apply z depth colormap based on z depths in slice
        zDepths = maxZ[i,nChannel,1]
        # TODO: make into functions for XY color assignment and XZ/YZ color assignment
        imBluesXY = np.zeros([lenY, lenX]).astype(int)
        imGreensXY = np.zeros([lenY, lenX]).astype(int)
        imRedsXY = np.zeros([lenY, lenX]).astype(int)
        for y in range(0,lenY):
            for x in range(0,lenX):
                zDepth = int(zDepths[y,x])
                imBluesXY[y,x] = zDepthColormap[zDepth][0]
                imGreensXY[y,x] = zDepthColormap[zDepth][1]
                imRedsXY[y,x] = zDepthColormap[zDepth][2]
        imBGRValsXY = cv2.merge([imBluesXY, imGreensXY, imRedsXY])

        frameXY = np.multiply(scaledImGrayscaleXY,imBGRValsXY).astype('uint8')


        # generate a scaled image for the XZ projection
        imXZ = copy.copy(maxY[i,nChannel])
        contrastedImXZ = adjustContrast(imXZ, adjMax, adjMin)
        scaledImGrayscaleXZ = invertAndScale(channel.name, contrastedImXZ)

        # apply z depth colormap based on z depths in slice
        imBluesXZ = np.zeros([lenZ, lenX]).astype(int)
        imGreensXZ = np.zeros([lenZ, lenX]).astype(int)
        imRedsXZ = np.zeros([lenZ, lenX]).astype(int)
        for z in range(0,lenZ):
            for x in range(0,lenX):
                zDepth = z
                imBluesXZ[z,x] = zDepthColormap[zDepth][0]
                imGreensXZ[z,x] = zDepthColormap[zDepth][1]
                imRedsXZ[z,x] = zDepthColormap[zDepth][2]
        imBGRValsXZ = cv2.merge([imBluesXZ, imGreensXZ, imRedsXZ])

        frameXZ = np.multiply(scaledImGrayscaleXZ,imBGRValsXZ).astype('uint8')
        frameXZ = np.flip(frameXZ, axis=0)

        # generate a scaled image for the YZ projection
        imYZ = copy.copy(np.transpose(maxX[i,nChannel]))
        contrastedImYZ = adjustContrast(imYZ, adjMax, adjMin)
        scaledImGrayscaleYZ = invertAndScale(channel.name, contrastedImYZ)

        # apply z depth colormap based on z depths in slice
        imBluesYZ = np.zeros([lenY, lenZ]).astype(int)
        imGreensYZ = np.zeros([lenY, lenZ]).astype(int)
        imRedsYZ = np.zeros([lenY, lenZ]).astype(int)
        for y in range(0,lenY):
            for z in range(0,lenZ):
                zDepth = z
                imBluesYZ[y,z] = zDepthColormap[zDepth][0]
                imGreensYZ[y,z] = zDepthColormap[zDepth][1]
                imRedsYZ[y,z] = zDepthColormap[zDepth][2]
        imBGRValsYZ = cv2.merge([imBluesYZ, imGreensYZ, imRedsYZ])

        frameYZ = np.multiply(scaledImGrayscaleYZ,imBGRValsYZ).astype('uint8')

        # initialize frame 
        frame = np.zeros([movieHeight,movieWidth,3]).astype('uint8')

        frame[0:lenZ,0:lenX,:] = frameXZ
        frame[(lenZ+gap):movieHeight,0:lenX,:] = frameXY
        frame[(lenZ+gap):movieHeight,(lenX+gap):movieWidth,:] = frameYZ

        #frame[np.where(scaledIm==0)] = [0,0,0]

        # time stamp
        t = f'{i*IMAGING_FREQ // 60:02d}' + ':' + f'{i*IMAGING_FREQ % 60:02d}'
        #cv2.putText(frame,t,(25,lenZ+gap+150),cv2.FONT_HERSHEY_SIMPLEX,6,[255,255,255],10,cv2.LINE_AA)
        cv2.putText(frame,t,(15,30),cv2.FONT_HERSHEY_SIMPLEX,1,[255,255,255],3,cv2.LINE_AA)

        # add scale bars
        scaleBarXY = scaleBar(
            posY = movieHeight - 76, #76
            posX = lenX - 468, #468
            height = 30, #30
            length = 416, #416
            text = '1 mm', #1 mm
            textOffset = 50, #50
        )
        scaleBarXY._addScaleBar(frame)

        # write frame 
        vid.write(frame)

    vid.release()
    cv2.destroyAllWindows()