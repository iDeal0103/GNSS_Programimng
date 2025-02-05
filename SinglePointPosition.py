# -*- coding: utf-8 -*-
"""

@title:	Style Guide for Python Code
@author: iDeal0103
@status:	Active
@type:	Process
@created:	14-Apr-2021
@post-History:	14-Apr-2021

comment：
    1.单点定位
    2.

"""

# import module
import numpy as np
import math
import datetime
import utils.DoFile as DoFile
import utils.SatellitePosition as SatellitePosition
import utils.TimeSystem as TimeSystem
import utils.CoorTransform as CoorTransform
import utils.RecordFilter as RecordFilter
import utils.const as const
from utils.ErrorReduction import *
import matplotlib.pyplot as plt
import utils.ResultAnalyse as ResultAnalyse
import utils.PictureResults as PictureResults
import sys


def cal_EmitTime_from_datetime(Tr, the_SVN, P, br_records, doCRC=True, c=299792458, system="G"):
    '''

    :param Tr: datetime.datetime , 观测站观测的GPS时刻
    :param the_SVN: str , 观测到卫星的SVN , "Gxx"
    :param P: 观测所得到的伪距(也可以是改正过的)
    :param br_records: list[GPS_brdc_record class] , 所使用的卫星广播星历记录
    :param doCRC: bool , 是否进行相对论效应改正
    :param c: float , 光速(单位 m/s)
    :return: ts: GPSws class , 得到卫星的信号发射时刻
    '''
    # 将datetime格式时间转换为精度更高的自定义GPSws时间类
    w, s = TimeSystem.from_datetime_cal_GPSws(Tr)
    Tr_GPSws = TimeSystem.GPSws(w, s)
    Ts = Tr_GPSws.cal_minus_result(P / c)

    # 以下标注的为有问题的计算方法 c!
    # # ts为考虑钟差的卫星发射时间
    # ts = Ts
    # t_del = 10
    # dts1 = 0
    # # 迭代计算发射时间
    # while abs(t_del) > 1e-8:
    #     # 计算卫星的钟差(单位为s)
    #     if doCRC:
    #         # 加入相对论钟差改正
    #         dts2 = SatellitePosition.cal_ClockError_GPSws(ts, the_SVN, br_records)
    #     else:
    #         dts2 = SatellitePosition.cal_ClockError_GPSws_withRelativisticEffect(ts, the_SVN, br_records)
    #     t_del = dts2 - dts1
    #     dts1 = dts2
    #     # 此处计算消除卫星钟差后的时间
    #     ts = Ts.cal_minus_result(dts2)
    # dts = dts2

    # 以下为正确的计算方法
    # 计算卫星的钟差(单位为s)
    if doCRC:
        # 加入相对论钟差改正
        dts2 = SatellitePosition.cal_ClockError_GPSws_withRelativisticEffect(Ts, the_SVN, br_records, system)
    else:
        dts2 = SatellitePosition.cal_ClockError_GPSws(Ts, the_SVN, br_records)
    # 此处计算消除卫星钟差后的时间
    ts = Ts.cal_minus_result(dts2)
    if doCRC:
        dts = SatellitePosition.cal_ClockError_GPSws_withRelativisticEffect(ts, the_SVN, br_records, system)
    else:
        dts = SatellitePosition.cal_ClockError_GPSws(ts, the_SVN, br_records)
    # for i in range(2):
    #     ts = ts.cal_minus_result(dts)
    #     dts = SatellitePosition.cal_ClockError_GPSws_withRelativisticEffect(ts, the_SVN, br_records)
    # ts = ts.cal_minus_result(5)
    # dts = SatellitePosition.cal_ClockError_GPSws(Ts, the_SVN, br_records)   # 进行相对论改正是可以给带来8m左右的精度提升(来源论文)
    # dts = dts2    # dts和dts2相差非常小,10e-15s量级

    return ts, dts


def observation_isnot_null(station_record, FreqBandList=['L1', 'C2']):
    '''
    station_record :  list[GPS_observation_record class] , 所使用观测文件读取 的各条记录
    FreqBandList : list[str] , 检查数据是否为空的频率波段 (如 'C1','L2','P1' )
    '''
    isnot_null_flags = []
    for band in FreqBandList:
        # 判断波段的数据是否齐全
        if not station_record.data.__contains__(band):
            isnot_null_flag = False
        elif station_record.data[band]['observation'] == "":
            isnot_null_flag = False
        else:
            isnot_null_flag = True
        isnot_null_flags.append(isnot_null_flag)
    if False in isnot_null_flags:
        result = False
    else:
        result = True
    return result


#基于广播星历数据进行单点定位
def SPP_on_GPS_broadcastrecords(ob_records, br_records, Tr, doIDC=True, doTDC=True, doCRC=True, recalP=False,
                                cutoff=30.123456, c=299792458, init_coor=[2000, 2000, 2000], excluded_sats=[], residual_plotter=""):
    """
    ob_records : GPS_observation_record , 所使用的观测文件记录
    br_records : GPS_brdc_record , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    doIDC : bool , 是否进行电离层改正
    doTDC : bool , 是否进行对流层改正
    doCRC : bool , 是否进行相对论钟差改正
    recalP : bool , 是否用高度角定权
    cutoff : float , 加入高度角限制条件,单位为度
    c : const , 光速(单位为m/s)
    init_coor : list , 观测站坐标初值
    """
    # 筛选出某时刻的记录
    cal_based_record = list(filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", ob_records))
    # 开始迭代前接收机钟差dtr为0
    dtr = 0
    # 初始地面点坐标
    Xk, Yk, Zk = init_coor
    no = 0
    Q=0
    v=0
    print(Tr)
    # 平差求解XYZ坐标和接收机钟差
    while True:
        # 如果超出平差迭代求解超出8次则跳出
        if no > 8:
            break
        # 计数
        no += 1
        # 初始化矩阵
        A = []
        l = []
        Ps = []
        for record in cal_based_record:
            # 如果所选观测值数据为空则跳过
            if not (record.managed_data_flag['L1_C'] and record.managed_data_flag['L2_C']):
                continue
            else:
                P = record.data['L1_C']['observation']
            the_svn = record.SVN

            '''根据接收时间,计算信号发射时间及此时卫星所在位置'''
            ts, dts = cal_EmitTime_from_datetime(Tr, the_svn, P, br_records, doCRC)

            # 修正地球自转影响
            coorX, coorY, coorZ = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts, the_svn, br_records)
            dt = P/c
            Xeci, Yeci, Zeci = CoorTransform.earth_rotation_correction([coorX, coorY, coorZ], dt)
            # dt2 = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])/c

            info = str(TimeSystem.from_GPSws_cal_datetime_2(ts)) + " sat=" + the_svn + " rs=" + str('%20.6f' % coorX) + " " + str('%20.6f' % coorY) + " " + str('%20.6f' % coorZ)
            ResultAnalyse.trace(info)

            # 检查高度角是否符合限差
            if no > 1 and cutoff != 30.123456:     # 考虑第一次迭代可能初值不准确，所以第二次后的迭代再加入截止角条件
                ele, a = CoorTransform.cal_ele_and_A([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                # print(ele *180 / math.pi, ele *180 / math.pi < cutoff)
                if ele *180 / math.pi < cutoff:
                    continue

            # 电离层改正
            if doIDC:
                P = Ionospheric_Delay_Correction(record, band1='L1_C', band2='L2_C')
            if doTDC:
                # 对流层延迟改正
                # P = Tropospheric_Delay_Correction_Hopfield(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                # P = Tropospheric_Delay_Correction_Saastamoinen(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                P = Tropospheric_Delay_Correction_UNB3(P, Tr, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])

            # 计算系数阵成分
            lou = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
            print(P-lou)
            if residual_plotter:
                res_record = PictureResults.plot_record(Tr, P-lou, the_svn)
                residual_plotter.add_plot_record(res_record)
            axki = (Xk-Xeci)/lou
            ayki = (Yk-Yeci)/lou
            azki = (Zk-Zeci)/lou
            # li = P-lou+c*(dts-dtr)
            li = P - lou + c * dts
            A.append([axki, ayki, azki, 1])
            l.append(li)
            # 构造权阵
            if recalP:
                # 计算Pq矩阵
                N, E, U = CoorTransform.cal_NEU([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                Pq = cal_P(N, E, U)
                Ps.append(Pq)
            else:
                Ps.append(1)
        # 求解
        if Ps == []:
            continue
        Pz = np.diag(Ps).astype('float')
        # 符合高度角条件的卫星数目不够
        if len(A) < 4:
            Xk, Yk, Zk = init_coor
            Q = -1
            no = 0
            break
        A = np.array(A).astype('float')
        l = np.array(l).astype('float')
        # 改正数发散太过严重则不再继续平差
        if abs(max(l.tolist())) > 1e8:
            no = 0
            Q = 10000
            break
        x = np.linalg.inv(A.T@Pz@A)@(A.T@Pz@l)
        print(no, ": ", len(Pz), "星", x)
        v = A@x-l
        # 更新参数
        dXk = x[0]
        dYk = x[1]
        dZk = x[2]
        # ddtr = x[3]/c
        dtr = x[3]/c
        Xk += dXk
        Yk += dYk
        Zk += dZk
        # dtr += ddtr
        Q = np.linalg.inv(A.T @ A)
        if abs(dXk) < 0.01 and abs(dYk) < 0.01 and abs(dZk) < 0.01:
            break
    return Xk, Yk, Zk, Q, v

def SPP_on_BDS_broadcastrecords(ob_records, br_records, Tr, doIDC=True, doTDC=True, doCRC=True, recalP=False,
                                cutoff=30.123456, c=299792458, init_coor=[2000, 2000, 2000], excluded_sats=[], residual_plotter=""):
    """
    ob_records : BDS_observation_record , 所使用的观测文件记录
    br_records : BDS_brdc_record , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    doIDC : bool , 是否进行电离层改正
    doTDC : bool , 是否进行对流层改正
    doCRC : bool , 是否进行相对论钟差改正
    recalP : bool , 是否用高度角定权
    cutoff : float , 加入高度角限制条件,单位为度
    c : const , 光速(单位为m/s)
    init_coor : list , 观测站坐标初值
    """
    # 筛选出某时刻的记录
    cal_based_record = list(filter(lambda o: o.SVN[0] == "C" and o.time == Tr and o.data != "", ob_records))
    # 开始迭代前接收机钟差dtr为0
    dtr = 0
    # 初始地面点坐标
    Xk, Yk, Zk = init_coor
    no = 0
    Q = 0
    v = 0
    print(Tr)
    # 平差求解XYZ坐标和接收机钟差
    while True:
        # 如果超出平差迭代求解超出8次则跳出
        if no > 8:
            break
        # 计数
        no += 1
        # 初始化矩阵
        A = []
        l = []
        Ps = []
        for record in cal_based_record:
            if record.SVN in excluded_sats:
                continue
            # 如果所选观测值数据为空则跳过
            if not (record.managed_data_flag['B1_C'] and record.managed_data_flag['B3_C']):
                continue
            else:
                P = record.data['B1_C']['observation']
            the_svn = record.SVN

            '''根据接收时间,计算信号发射时间及此时卫星所在位置'''
            ts, dts = cal_EmitTime_from_datetime(Tr, the_svn, P, br_records, doCRC, system="C")

            # 修正地球自转影响
            coorX, coorY, coorZ = SatellitePosition.cal_SatellitePosition_BDS_GPSws(ts, the_svn, br_records)
            # coorX, coorY, coorZ = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts, the_svn, br_records)
            dt = P/c
            Xeci, Yeci, Zeci = CoorTransform.earth_rotation_correction([coorX, coorY, coorZ], dt, system='C')
            # dt2 = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])/c

            info = str(TimeSystem.from_GPSws_cal_datetime_2(ts)) + " sat=" + the_svn + " rs=" + str('%20.6f' % coorX) + " " + str('%20.6f' % coorY) + " " + str('%20.6f' % coorZ)
            ResultAnalyse.trace(info)

            # 检查高度角是否符合限差
            if no > 1 and cutoff != 30.123456:     # 考虑第一次迭代可能初值不准确，所以第二次后的迭代再加入截止角条件
                ele, a = CoorTransform.cal_ele_and_A([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                # print(ele *180 / math.pi, ele *180 / math.pi < cutoff)
                if ele * 180 / math.pi < cutoff:
                    continue

            # 电离层改正
            if doIDC:
                P = Ionospheric_Delay_Correction(record, 'B1_C', 'B3_C', 1575.42, 1268.52)
            if doTDC:
                # 对流层延迟改正
                # P = Tropospheric_Delay_Correction_Hopfield(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                # P = Tropospheric_Delay_Correction_Saastamoinen(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                P = Tropospheric_Delay_Correction_UNB3(P, Tr, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])

            # 计算系数阵成分
            lou = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
            if residual_plotter:
                res_record = PictureResults.plot_record(Tr, P-lou, the_svn)
                residual_plotter.add_plot_record(res_record)
            axki = (Xk-Xeci)/lou
            ayki = (Yk-Yeci)/lou
            azki = (Zk-Zeci)/lou
            li = P - lou + c * dts
            A.append([axki, ayki, azki, 1])
            l.append(li)
            # 构造权阵
            if recalP:
                # 计算Pq矩阵
                N, E, U = CoorTransform.cal_NEU([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                Pq = cal_P(N, E, U)
                Ps.append(Pq)
            else:
                Ps.append(1)
        # 求解
        if Ps == []:
            continue
        Pz = np.diag(Ps).astype('float')
        # 符合高度角条件的卫星数目不够
        if len(A) < 4:
            Xk, Yk, Zk = init_coor
            Q = -1
            no = 0
            break
        A = np.array(A).astype('float')
        l = np.array(l).astype('float')
        # 改正数发散太过严重则不再继续平差
        if abs(max(l.tolist())) > 1e8:
            no = 0
            Q = 10000
            break
        x = np.linalg.inv(A.T@Pz@A)@(A.T@Pz@l)
        print(no, ": ", len(Pz), "星", x)
        v = A@x-l
        # 更新参数
        dXk = x[0]
        dYk = x[1]
        dZk = x[2]
        # ddtr = x[3]/c
        dtr = x[3]/c
        Xk += dXk
        Yk += dYk
        Zk += dZk
        # dtr += ddtr
        Q = np.linalg.inv(A.T @ A)
        if abs(dXk) < 0.01 and abs(dYk) < 0.01 and abs(dZk) < 0.01:
            break
    return Xk, Yk, Zk, Q, v


# 基于多系统广播星历数据进行单点定位，目前支持GPS+BDS
def SPP_on_mixed_broadcastrecords(ob_records, br_records, Tr, doIDC=True, doTDC=True, doCRC=True, recalP=False,
                            cutoff=30.123456, c=299792458, init_coor=[2000, 2000, 2000], include_system=['G','C'], excluded_sats=[]):
    """
    ob_records : GPS/BDS_observation_record , 所使用的观测文件记录
    br_records : GPS/BDS_brdc_record , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    doIDC : bool , 是否进行电离层改正
    doTDC : bool , 是否进行对流层改正
    doCRC : bool , 是否进行相对论钟差改正
    recalP : bool , 是否用高度角定权
    cutoff : float , 加入高度角限制条件,单位为度
    c : const , 光速(单位为m/s)
    init_coor : list , 观测站坐标初值
    """
    # 筛选出某时刻的记录
    cal_based_record = list(filter(lambda o:(o.SVN[0] == 'G' or o.SVN[0] == 'C') and o.time == Tr and o.data != "", ob_records))
    # 开始迭代前接收机钟差dtr为0
    dtr_gps = 0
    dtr_bds = 0
    # 初始地面点坐标
    Xk, Yk, Zk = init_coor
    no = 0
    Q=0
    v=0
    # 平差求解XYZ坐标和接收机钟差
    while True:
        # 如果超出平差迭代求解超出8次则跳出
        if no > 8:
            break
        # 计数
        no += 1
        # 初始化矩阵
        A = []
        l = []
        Ps = []
        for record in cal_based_record:
            if record.SVN in excluded_sats:
                continue
            # GPS系统
            if record.SVN[0] == 'G' and 'G' in include_system:
                # 如果所选观测值数据为空则跳过
                if not observation_isnot_null(record, ['L1_C', 'L2_C']):
                    continue
                else:
                    P = record.data['L1_C']['observation']
                the_svn = record.SVN
                # print(Tr, the_svn, type(P), P)

                '''根据接收时间,计算信号发射时间及此时卫星所在位置'''
                ts, dts = cal_EmitTime_from_datetime(Tr, the_svn, P, br_records, doCRC)

                # 修正地球自转影响
                coorX, coorY, coorZ = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts, the_svn, br_records)
                dt = P/c
                Xeci, Yeci, Zeci=CoorTransform.earth_rotation_correction([coorX, coorY, coorZ], dt)
                # 电离层改正
                if doIDC:
                    P = Ionospheric_Delay_Correction(record, 'L1_C', 'L2_C', 1575.42, 1227.60)

                # 检查高度角是否符合限差
                if no > 1 and cutoff != 30.123456:  # 考虑第一次迭代可能初值不准确，所以第二次后的迭代再加入截止角条件
                    ele, a = CoorTransform.cal_ele_and_A([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # print(ele * 180 / math.pi, ele * 180 / math.pi < cutoff)
                    if ele * 180 / math.pi < cutoff:
                        continue

                if doTDC:
                    # 对流层延迟改正
                    # P = Tropospheric_Delay_Correction_Hopfield(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # P = Tropospheric_Delay_Correction_Saastamoinen(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    P = Tropospheric_Delay_Correction_UNB3(P, Tr, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                # 计算系数阵成分
                lou = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                axki = (Xk - Xeci) / lou
                ayki = (Yk - Yeci) / lou
                azki = (Zk - Zeci) / lou
                # li = P-lou+c*(dts-dtr)
                li = P - lou + c * dts
                A.append([axki, ayki, azki, 1, 0])
                l.append(li)
                # 构造权阵
                if recalP:
                    # 计算Pq矩阵
                    N, E, U = CoorTransform.cal_NEU([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    Pq = cal_P(N, E, U)
                    Ps.append(Pq)
                else:
                    Ps.append(1)

            # BDS系统
            elif record.SVN[0] == 'C' and 'C' in include_system:
                # 如果所选观测值数据为空则跳过
                if not observation_isnot_null(record, ['B1_C', 'B3_C']):
                    continue
                else:
                    P = record.data['B1_C']['observation']
                the_svn = record.SVN
                # print(Tr, the_svn, type(P), P)

                '''根据接收时间,计算信号发射时间及此时卫星所在位置'''
                ts, dts = cal_EmitTime_from_datetime(Tr, the_svn, P, br_records, doCRC)

                # 修正地球自转影响
                coorX, coorY, coorZ = SatellitePosition.cal_SatellitePosition_BDS_GPSws(ts, the_svn, br_records)
                dt = P / c
                Xeci, Yeci, Zeci = CoorTransform.earth_rotation_correction([coorX, coorY, coorZ], dt)
                # 电离层改正
                if doIDC:
                    P = Ionospheric_Delay_Correction(record, 'B1_C', 'B3_C', 1575.42, 1268.52)

                # 检查高度角是否符合限差
                if no > 1 and cutoff != 30.123456:  # 考虑第一次迭代可能初值不准确，所以第二次后的迭代再加入截止角条件
                    ele, a = CoorTransform.cal_ele_and_A([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # print(ele * 180 / math.pi, ele * 180 / math.pi < cutoff)
                    if ele * 180 / math.pi < cutoff:
                        continue

                if doTDC:
                    # 对流层延迟改正
                    # P = Tropospheric_Delay_Correction_Hopfield(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # P = Tropospheric_Delay_Correction_Saastamoinen(P, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    P = Tropospheric_Delay_Correction_UNB3(P, Tr, [Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # doy = cal_doy(Tr)
                    # ele, a = CoorTransform.cal_ele_and_A([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    # B,L,H = CoorTransform.cal_XYZ2BLH(Xk, Yk, Zk)
                    # M = Niell(B, H, ele, doy)
                    # D = UNB3(B, H, doy)
                    # dtrop = M[0] * D[0] + M[1] * D[1]
                    # P -= dtrop
                # 计算系数阵成分
                lou = CoorTransform.cal_distance([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                axki = (Xk - Xeci) / lou
                ayki = (Yk - Yeci) / lou
                azki = (Zk - Zeci) / lou
                # li = P-lou+c*(dts-dtr)
                li = P - lou + c * dts
                A.append([axki, ayki, azki, 0, 1])
                l.append(li)
                # 构造权阵
                if recalP:
                    # 计算Pq矩阵
                    N, E, U = CoorTransform.cal_NEU([Xk, Yk, Zk], [Xeci, Yeci, Zeci])
                    Pq = cal_P(N, E, U)
                    if the_svn in ["C01", "C02", "C03", "C04", "C05", "C59", "C60"]:
                        Ps.append(0.5 * Pq)
                    else:
                        Ps.append(Pq)
                else:
                    if the_svn in ["C01", "C02", "C03", "C04", "C05", "C59", "C60"]:
                        Ps.append(0.5)
                    else:
                        Ps.append(1)
        # 求解
        if Ps == []:
            continue
        Pz = np.diag(Ps).astype('float')
        # 符合高度角条件的卫星数目不够
        if len(A) < 4:
            Xk, Yk, Zk = init_coor
            Q = -1
            no = 0
            break
        A = np.array(A).astype('float')
        l = np.array(l).astype('float')
        # 改正数发散太过严重则不再继续平差
        if abs(max(l.tolist())) > 1e10:
            no = 0
            Q = 10000
            break
        x = np.linalg.inv(A.T@Pz@A)@(A.T@Pz@l)
        print(no, ": ", len(Pz), "星", x)
        v = A@x-l
        # 更新参数
        dXk = x[0]
        dYk = x[1]
        dZk = x[2]
        # ddtr = x[3]/c
        dtr_gps = x[3]/c
        dtr_bds = x[4]/c
        Xk += dXk
        Yk += dYk
        Zk += dZk
        Q = np.linalg.inv(A.T @ A)
        if abs(dXk) < 0.01 and abs(dYk) < 0.01 and abs(dZk) < 0.01:
            break
    return Xk, Yk, Zk, Q, v


# 权函数
def cal_P(N, E, U):
    R = math.sqrt(N ** 2 + E ** 2 + U ** 2)
    A = math.atan2(E, N)
    Ez = math.asin(U / R)
    # 定权方法1
    if Ez > math.pi / 6:
        P = 1
    else:
        P = 2 * math.sin(Ez)
    # #定权方法2
    # P=sin(E)**2
    return P


# 计算GDOP
def cal_GDOP(QXYZt):  # QXYZt或QNEUt
    GDOP = math.sqrt(QXYZt[0, 0] + QXYZt[1, 1] + QXYZt[2, 2] + QXYZt[3, 3])
    return GDOP


# 计算PDOP
def cal_PDOP(QXYZt):  # QXYZt或QNEUt
    PDOP = math.sqrt(QXYZt[0, 0] + QXYZt[1, 1] + QXYZt[2, 2])
    return PDOP


# 计算TDOP
def cal_TDOP(QXYZt):  # QXYZt或QNEUt
    TDOP = math.sqrt(QXYZt[3, 3])
    return TDOP


# 由QXYZt计算QNEUt
def cal_QNEUt(X, Y, Z, QXYZt):
    R = CoorTransform.cal_R_THS2TES([X, Y, Z])  # 站心地平坐标系到站心赤道坐标系的旋转矩阵
    T = np.linalg.inv(R)  # 站心赤道坐标系站到地心地平坐标系的旋转矩阵
    QXYZ = QXYZt[:3, :3]
    QNEU = T @ QXYZ @ T.T
    QNEUt = QXYZt
    QNEUt[:3, :3] = QNEU
    return QNEUt


# 计算HDOP
def cal_HDOP(QNEUt):
    HDOP = math.sqrt(QNEUt[0, 0] + QNEUt[1, 1])
    return HDOP


# 计算VDOP
def cal_VDOP(QNEUt):
    VDOP = math.sqrt(QNEUt[2, 2])
    return VDOP


# 计算(并绘制)NEU误差序列
def cal_NEUerrors(true_coors, cal_coors, form="plot", ylimit=None, T_series="", save_path=""):
    """
        true_coors : [[Xs,Ys,Zs],……],真实坐标列表
        cal_coors : [[Xa,Ya,Za],……],计算坐标列表
        save_path ： 绘图存储
    """
    delta_N = []
    delta_E = []
    delta_U = []
    for i in range(len(true_coors)):
        n, e, u = CoorTransform.cal_NEU(true_coors[i], cal_coors[i])
        delta_N.append(n)
        delta_E.append(e)
        delta_U.append(u)
    # 绘图
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    if not T_series:
        if form == "scatter":
            plt.scatter([i for i in range(len(delta_U))], delta_U, color="b", label="U")
            plt.scatter([i for i in range(len(delta_N))], delta_N, color="r", label="N")
            plt.scatter([i for i in range(len(delta_E))], delta_E, color="g", label="E")
            plt.xlabel("epoch", fontsize=15)
        elif form == "plot":
            plt.plot(delta_U, color="b", label="U")
            plt.plot(delta_N, color="r", label="N")
            plt.plot(delta_E, color="g", label="E")
            plt.xlabel("epoch", fontsize=15)
    else:
        if form == "scatter":
            plt.scatter(T_series, delta_U, color="b", label="U")
            plt.scatter(T_series, delta_N, color="r", label="N")
            plt.scatter(T_series, delta_E, color="g", label="E")
            plt.xlabel("GPST", fontsize=15)
        elif form == "plot":
            plt.plot(T_series, delta_U, color="b", label="U")
            plt.plot(T_series, delta_N, color="r", label="N")
            plt.plot(T_series, delta_E, color="g", label="E")
            plt.xlabel("GPST", fontsize=15)
    plt.ylabel('各方向定位误差/m', fontsize=15)
    plt.legend(loc='upper right', fontsize=17)
    plt.xticks(fontsize=15)
    plt.yticks(fontsize=15)
    plt.title("NEU误差序列图")
    plt.grid()
    if save_path != "":
        plt.savefig(save_path)
    if ylimit:
        plt.ylim(-ylimit, ylimit)
    plt.show()
    return delta_N, delta_E, delta_U


def cal_XYZerrors(true_coors, cal_coors, form="plot", ylimit=None, T_series="", save_path=""):
    """
        true_coors : [[Xs,Ys,Zs],……],真实坐标列表
        cal_coors : [[Xa,Ya,Za],……],计算坐标列表
        save_path ： 绘图存储
    """
    delta_X = []
    delta_Y = []
    delta_Z = []
    for i in range(len(true_coors)):
        dX = cal_coors[i][0] - true_coors[i][0]
        dY = cal_coors[i][1] - true_coors[i][1]
        dZ = cal_coors[i][2] - true_coors[i][2]
        delta_X.append(dX)
        delta_Y.append(dY)
        delta_Z.append(dZ)
    # 绘图
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    if not T_series:
        if form == "scatter":
            plt.scatter([i for i in range(len(delta_X))], delta_X, color="r", label="X")
            plt.scatter([i for i in range(len(delta_Y))], delta_Y, color="g", label="Y")
            plt.scatter([i for i in range(len(delta_Z))], delta_Z, color="b", label="Z")
            plt.xlabel("epoch", fontsize=15)
        elif form == "plot":
            plt.plot(delta_X, color="r", label="X")
            plt.plot(delta_Y, color="g", label="Y")
            plt.plot(delta_Z, color="b", label="Z")
            plt.xlabel("epoch", fontsize=15)
    else:
        if form == "scatter":
            plt.scatter(T_series, delta_X, color="r", label="X")
            plt.scatter(T_series, delta_Y, color="g", label="Y")
            plt.scatter(T_series, delta_Z, color="b", label="Z")
            plt.xlabel("GPST", fontsize=15)
        elif form == "plot":
            plt.plot(T_series, delta_X, color="r", label="X")
            plt.plot(T_series, delta_Y, color="g", label="Y")
            plt.plot(T_series, delta_Z, color="b", label="Z")
            plt.xlabel("GPST", fontsize=15)
    plt.ylabel('各方向定位误差/m', fontsize=15)
    plt.legend(loc='upper right', fontsize=17)
    plt.title("XYZ误差序列图")
    plt.xticks(fontsize=15)
    plt.yticks(fontsize=15)
    plt.grid()
    if ylimit:
        plt.ylim(-ylimit, ylimit)
    if save_path != "":
        plt.savefig(save_path)
    plt.show()
    return delta_X, delta_Y, delta_Z


def cal_Coorerrors(true_coors, cal_coors, ylimit=None, save_path=""):
    """
        true_coors : [[Xs,Ys,Zs],……],真实坐标列表
        cal_coors : [[Xa,Ya,Za],……],计算坐标列表
        save_path ： 绘图存储
    """
    delta_d = []
    for i in range(len(true_coors)):
        dX = cal_coors[i][0] - true_coors[i][0]
        dY = cal_coors[i][1] - true_coors[i][1]
        dZ = cal_coors[i][2] - true_coors[i][2]
        delta_d.append(math.sqrt(dX**2 + dY**2 + dZ**2))
    # 绘图
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    plt.plot(delta_d, color="turquoise", label="delta d / m")
    plt.legend(loc='upper right')
    plt.title("坐标误差序列图")
    if ylimit:
        plt.ylim(-ylimit, ylimit)
    if save_path != "":
        plt.savefig(save_path)
    plt.show()
    return delta_d


# 计算NEU误差
def cal_NEUerror(true_coor, cal_coor):
    """
        true_coors : [Xs,Ys,Zs]真实坐标
        cal_coors : [Xa,Ya,Za]计算坐标
    """
    dn, de, du = CoorTransform.cal_NEU(true_coor, cal_coor)
    return dn, de, du






if __name__=="__main__":

    sys.stderr=open(r"D:\Desktop\pnt2_bds.txt", "w")
    Presidual_plotter = PictureResults.plot_records_manager("P-lou")

    # observation_file=r"E:\大三下\卫星与导航定位\代码集合\Satellite_Navigation_and_Positioning\data\obs\warn3100.20o"
    # observation_file = r"edata\obs\leij3100.20o"
    # observation_file = r"edata\obs\chan3100.20o"
    # observation_file = r"edata\obs\wab23100.20o"
    # observation_file = r"edata\obs\warn3100.20o"
    # observation_file = r"edata\obs\warn3120.20o"
    # observation_file = r"edata\obs\zimm3100.20o"  # zimm
    # observation_file = r"edata\obs\zim23100.20o"  # zim2
    observation_file = r"edata\obs\rinex3\WARN00DEU_R_20203100000_01D_30S_MO.rnx"
    # broadcast_file = r"edata\sat_obit\brdc3100.20n"
    # broadcast_file = r"edata\sat_obit\brdc3120.20n"
    broadcast_file = r"edata\sat_obit\BRDM00DLR_S_20203100000_01D_MN.rnx"
    # igs_file=r"E:\大三下\卫星与导航定位\代码集合\Satellite_Navigation_and_Positioning\data\sat_obit\igs21304.sp3"
    # clk_file=r"F:\360MoveData\Users\hp\Desktop\emr21304.clk"
    # 读入观测文件内容,得到类型对象列表
    # ob_records = DoFile.read_Rinex2_oFile(observation_file)
    ob_records = DoFile.read_Rinex3_oFile(observation_file)
    # br_records = DoFile.read_GPS_nFile(broadcast_file)
    br_records = DoFile.read_Renix304_nFile(broadcast_file)
    # br_records = RecordFilter.GPSBrdcRecord_HourIntegerRecord_Filter(br_records)
    # pe_records=DoFile.read_GPS_sp3File(igs_file)
    # clk_records=DoFile.read_GPS_clkFile(clk_file)[0]
    # 给入选定时刻
    Tr = datetime.datetime(2020, 11, 5, 16, 0, 0)
    init_coor=[3658785.6000, 784471.1000, 5147870.7000]   #warn
    # init_coor=[-2674431.9143, 3757145.2969, 4391528.8732]   #chan
    # init_coor = [10, 10, 10]
    # init_coor = [4331297.3480, 567555.6390, 4633133.7280]  # zimm
    # init_coor = [4331300.1600, 567537.0810, 4633133.5100]  # zim2
    # init_coor = [4327318.2325, 566955.9585, 4636425.9246]  # wab2
    true_coors = []
    cal_coors = []
    vs = []
    while Tr < datetime.datetime(2020, 11, 5, 20, 0, 0):
        # Xk,Yk,Zk,Q=SPP.SPP_on_broadcastfile(observation_file,broadcast_file,Tr)
        # Xk, Yk, Zk, Q, v = SPP_on_GPS_broadcastrecords(ob_records, br_records, Tr, init_coor=init_coor, recalP=True, doTDC=True, doIDC=True, residual_plotter=Presidual_plotter)
        Xk, Yk, Zk, Q, v = SPP_on_BDS_broadcastrecords(ob_records, br_records, Tr, init_coor=init_coor, recalP=True, doTDC=True, doIDC=True,excluded_sats=['C56','C57','C58'], residual_plotter=Presidual_plotter)
        # Xk, Yk, Zk, Q, v = SPP_on_mixed_broadcastrecords(ob_records, br_records, Tr, cutoff=15, init_coor=init_coor,
        #                                            recalP=True, doTDC=True, doIDC=True, excluded_sats=['C56', 'C57', 'C58'])
        cal_coors.append([Xk, Yk, Zk])
        vs.append(v)
        # print(Xk, Yk, Zk, Q, v)
        true_coors.append([0.365878555276965E+07, 0.784471127238666E+06, 0.514787071062059E+07])  #warn
        # true_coors.append([4331297.3480, 567555.6390, 4633133.7280])  # zimm
        # true_coors.append([4331300.1600, 567537.0810, 4633133.5100])  # zim2
        # true_coors.append([0.389873613453103E+07,0.855345521080705E+06,0.495837257579542E+07])   #leij
        # true_coors.append([-0.267442768572702E+07, 0.375714305701559E+07, 0.439152148514515E+07])  #chan
        # true_coors.append([4327318.2325, 566955.9585, 4636425.9246])  # wab2
        Tr += datetime.timedelta(seconds=30)
    cal_NEUerrors(true_coors, cal_coors)
    cal_XYZerrors(true_coors, cal_coors)
    # plt.plot(vs)
    # plt.show()
    print("neu各方向RMSE:", ResultAnalyse.get_NEU_rmse(true_coors, cal_coors))
    print("坐标RMSE:", ResultAnalyse.get_coor_rmse(true_coors, cal_coors))
    Presidual_plotter.plot_all_records()












