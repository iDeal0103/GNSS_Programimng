


# import module
import numpy as np
import SinglePointPosition as SPP
import math
import datetime
import utils.DoFile as DoFile
import utils.SatellitePosition as SatellitePosition
import utils.TimeSystem as TimeSystem
import utils.CoorTransform as CoorTransform
from utils.ErrorReduction import *
import matplotlib.pyplot as plt
from utils.const import *
import utils.LAMBDA as LAMBDA
from utils.MultiFrequencyCombinations import get_widelane_combination
from RTK import *


def get_symmetric_matrix(matrix, threshold=10e-1):
    if ((matrix - matrix.T) < threshold).all():
        sysmmetric_matrix = (matrix + matrix.T)/2
        return sysmmetric_matrix
    else:
        print('matrix is not sysmmetric!')
        return matrix


# 基于载波相位+伪距的双差，单历元 (其中一个观测站为已知坐标站点)
def DD_onCarrierPhase_and_Pseudorange_1known(station1_ob_records, station2_ob_records, br_records,
                                             Tr, station1_init_coor, station2_init_coor, CRC=True, cutoff=15.12345678,
                                             c=299792458, ambi_fix=False, bands=['L1_L', 'L2_C']):
    """
    station1_ob_records : list[GPS_observation_record class] , 所使用的观测站1观测文件记录
    station2_ob_records : list[GPS_observation_record class] , 所使用的观测站2观测文件记录
    br_records :  list[GPS_brdc_record class] , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    station1_init_coor : list , 观测站1坐标已知值
    CRC : bool , 是否进行相对论钟差改正
    c : const , 光速(单位为m/s)
    ambi_fix : bool , 是否进行模糊度固定
    station2_init_coor : list , 观测站2坐标初值
    """
    # 载波相位和伪距相位
    cp_band = bands[0]
    pr_band = bands[1]

    # 筛选出两个站点的观测记录
    station1_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station1_ob_records))
    station2_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station2_ob_records))

    # 选择相邻两个历元均存在的四颗卫星
    available_SVNs = []
    original_SVNS = []
    for station2_record in station2_ob_records:
        original_SVNS.append(station2_record.SVN)
        # 对station1_ob_record进行同一颗卫星的筛选
        station1_record_base = list(filter(lambda o: o.SVN == station2_record.SVN, station1_ob_records))
        if len(station1_record_base) != 1:
            continue
        else:
            if (observation_isnot_null(station1_record_base[0], bands) and observation_isnot_null(station2_record, bands)):
                available_SVNs.append(station2_record.SVN)
            else:
                continue

    # 判断卫星数是否足够
    num_flag = True
    print("all satellite:", original_SVNS)
    print("the abled satellite:", available_SVNs)
    ob_num = len(available_SVNs)
    if ob_num < 4:
        num_flag = False
    elif ob_num >= 4:
        num_flag = True

    # 卫星数足够，则开始迭代进行双差观测的平差求解
    # if num_flag == False:
    #     return
    if num_flag:
        # 初始地面点坐标
        X1, Y1, Z1 = station1_init_coor
        X2, Y2, Z2 = station2_init_coor
        Qcoor = 0
        # 载波的波长
        lamb = get_lamb_from_band(cp_band)
        # 平差迭代次数计数
        no = 0

        # 先大致计算各卫星所在位置(注:必须在站的初始位置较靠近真实坐标时才有效)
        satellite_ele = {}
        Tr_GPSws = TimeSystem.GPSws(TimeSystem.from_datetime_cal_GPSws(Tr)[0], TimeSystem.from_datetime_cal_GPSws(Tr)[1])
        for SVN in available_SVNs:
            coorX_Tr, coorY_Tr, coorZ_Tr = SatellitePosition.cal_SatellitePosition_GPS_GPSws(Tr_GPSws, SVN, br_records)
            ele_sta1_Tr = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
            ele_sta2_Tr = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
            ele_total = ele_sta1_Tr + ele_sta2_Tr
            satellite_ele[SVN] = ele_total
        # 根据高度角选择最合适的基准卫星, 以及确定其他卫星
        the_SVN = max(zip(satellite_ele.values(), satellite_ele.keys()))[1]
        diff_SVNs = available_SVNs
        diff_SVNs.remove(the_SVN)

        while True:
            # 如果超出平差迭代求解超出8次则跳出
            if no > 8:
                break
            no += 1
            final_SVNs = []

            # 初始化各观测值矩阵
            A1 = []
            l1 = []
            A2 = []
            l2 = []

            P = []

            # 获取卫星1的两站观测记录
            station1_base_record = list(filter(lambda o: o.SVN == the_SVN, station1_ob_records))[0]
            station2_base_record = list(filter(lambda o: o.SVN == the_SVN, station2_ob_records))[0]

            for available_PRN in diff_SVNs:  # 卫星2

                """
                根据PRN对第一个历元两个站观测记录的的筛选
                """

                station1_record = list(filter(lambda o: o.SVN == available_PRN, station1_ob_records))[0]
                station2_record = list(filter(lambda o: o.SVN == available_PRN, station2_ob_records))[0]

                # 构造双差方程
                L1obs_sta1sat1 = station1_base_record.data[cp_band]['observation']
                L1obs_sta2sat1 = station2_base_record.data[cp_band]['observation']
                L1obs_sta1sat2 = station1_record.data[cp_band]['observation']
                L1obs_sta2sat2 = station2_record.data[cp_band]['observation']

                P1obs_sta1sat1 = station1_base_record.data[pr_band]['observation']
                P1obs_sta2sat1 = station2_base_record.data[pr_band]['observation']
                P1obs_sta1sat2 = station1_record.data[pr_band]['observation']
                P1obs_sta2sat2 = station2_record.data[pr_band]['observation']

                # 计算卫星发出信号时刻及发出信号时刻在ECEF坐标系中的位置，以及信号发射时刻站星距离
                # 站1到卫星1
                ts_sta1sat1_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station1_base_record.data[pr_band]['observation'], br_records, doCRC=True)
                coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat1_Tr1, the_SVN, br_records)
                dt_sta1sat1_Tr1 = station1_base_record.data[pr_band]['observation'] / c
                # dt_sta1sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat1_Tr1.GpsSecond
                Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1], dt_sta1sat1_Tr1)
                lou_sta1sat1_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1])
                ele = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站2到卫星1
                ts_sta2sat1_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station2_base_record.data[pr_band]['observation'], br_records, doCRC=True)
                coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat1_Tr1, the_SVN, br_records)
                dt_sta2sat1_Tr1 = station2_base_record.data[pr_band]['observation'] / c
                # dt_sta2sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat1_Tr1.GpsSecond
                Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1], dt_sta2sat1_Tr1)
                lou_sta2sat1_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1])
                ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站1到卫星2
                ts_sta1sat2_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station1_record.data[pr_band]['observation'], br_records, doCRC=True)
                coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat2_Tr1, available_PRN, br_records)
                dt_sta1sat2_Tr1 = station1_record.data[pr_band]['observation']/c
                # dt_sta1sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat2_Tr1.GpsSecond
                Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1], dt_sta1sat2_Tr1)
                lou_sta1sat2_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1])
                ele =CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站2到卫星2
                ts_sta2sat2_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station2_record.data[pr_band]['observation'], br_records, doCRC=True)
                coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat2_Tr1, available_PRN, br_records)
                dt_sta2sat2_Tr1 = station2_record.data[pr_band]['observation']/c
                # dt_sta2sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat2_Tr1.GpsSecond
                Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1], dt_sta2sat2_Tr1)
                lou_sta2sat2_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1])
                ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                final_SVNs.append(available_PRN)

                """
                  构造矩阵阵
                """
                # 构造相位部分系数阵和常数阵
                a_sta2_X = (X2 - Xeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (X2 - Xeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                a_sta2_Y = (Y2 - Yeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (Y2 - Yeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                a_sta2_Z = (Z2 - Zeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (Z2 - Zeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                A_part1 = [a_sta2_X, a_sta2_Y, a_sta2_Z]
                l_part1 = lamb * (L1obs_sta2sat2 - L1obs_sta1sat2 - L1obs_sta2sat1 + L1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10

                # 构造伪距部分系数阵和常数阵
                A_part2 = [a_sta2_X, a_sta2_Y, a_sta2_Z]
                # 构造常数阵
                l_part2 = (P1obs_sta2sat2 - P1obs_sta1sat2 - P1obs_sta2sat1 + P1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10

                # 如果两个部分均符合要求，则加入各历元对应的矩阵中
                A1.append(A_part1)
                l1.append(l_part1)
                A2.append(A_part2)
                l2.append(l_part2)
                P.append(P1obs_sta2sat2 - P1obs_sta1sat2 - P1obs_sta2sat1 + P1obs_sta1sat1)

            qualitified_num = len(l1) + len(l2)
            if qualitified_num < 4:
                qualitified_flag = False
            elif qualitified_num >= 4:
                qualitified_flag = True

            if not qualitified_flag:
                X2, Y2, Z2 = station2_init_coor
                Qcoor = 10000
                break

            # 构造系数阵
            A = []
            for i in range(len(l1)):
                N_DD = make_Ambiguity_coefficient_matrix_row(i, len(l1), lamb)
                A.append(A1[i]+N_DD)
            for i in range(len(l2)):
                N_DD = [0 for i in range(len(l2))]
                A.append(A2[i]+N_DD)

            # 构造权阵并求解
            # Ps1 = get_DD_Pmatrix(len(l1), 1000)     # 相位
            # Ps2 = get_DD_Pmatrix(len(l2), 1)     # 伪距
            Ps1 = np.linalg.inv(get_DD_Qmatrix(len(l1), 0.002))     # 相位
            Ps2 = np.linalg.inv(get_DD_Qmatrix(len(l2), 1))     # 伪距

            Pz = diagonalize_squarematrix(Ps1, Ps2)
            A = np.array(A)
            l = np.array(l1 + l2)

            # 改正数发散太过严重则不再继续平差
            if abs(max(l.tolist())) > 1e10:
                break
            x = np.linalg.inv(A.T @ Pz @ A) @ (A.T @ Pz @ l)
            Q = np.linalg.inv(A.T @ Pz @ A).astype(float)
            V = A @ x - l
            sigma0 = math.sqrt((V.T @ Pz @ V)/(len(l1)-3))
            Qs = Q
            # Qs = sigma0**2 * Q
            Qcoor = Q[:3, :3]

            # 更新参数
            dX2 = x[0]
            dY2 = x[1]
            dZ2 = x[2]
            N_float = x[3:]
            X2 += dX2
            Y2 += dY2
            Z2 += dZ2

            # 计算残差
            residual = V

            print(no, ": ", len(Pz)/2, "组 多余观测：", len(Pz)/2-3, [dX2, dY2, dZ2])
            print("    differenced satellite:", final_SVNs)
            # 判断迭代停止条件
            if abs(dX2) < 1e-4 and abs(dY2) < 1e-4 and abs(dZ2) < 1e-4:
                break

        # 进行模糊度固定
        if ambi_fix and qualitified_flag:
            # 调用LAMBDA方法进行整数估计
            Qaa = get_symmetric_matrix(Q[3:, 3:])
            Qba = Q[:3, 3:]
            N_fixed, sqnorm, Ps, Qzhat, Z, nfixed, mu = LAMBDA.main(N_float, Qaa)
            # 更新参数估计
            b_hat = np.array([X2, Y2, Z2])
            a_hat = N_float
            Coor = MAPmethod(b_hat, a_hat, Qaa, Qba, N_fixed[:, 0])
            X2, Y2, Z2 = Coor
            # todo 计算MAP计算后的坐标方差
        else:
            Coor = [X2, Y2, Z2]

    # 如果没有足够的卫星
    else:
        X2 ,Y2, Z2 = station2_init_coor
        Qcoor = 10000
        Qs = 0
        N_float=[]
        the_SVN=""
        final_SVNs=[]
        P=[]
        residual=[]

    return [X2, Y2, Z2], Qs, N_float, the_SVN, final_SVNs, P, residual



# 给定坐标值，求解模糊度
def DD_onCPandPR_solve_ambiguity(station1_ob_records, station2_ob_records, br_records,
                                 Tr, station1_coor, station2_coor, cutoff=15.12345678,
                                 c=299792458, bands=['L1_L', 'L2_C'], DDambiguity_manager=None, DDobs_residual_manager=None,
                                 prnoise_manager=None, ele_manager=None):
    """
    station1_ob_records : list[GPS_observation_record class] , 所使用的观测站1观测文件记录
    station2_ob_records : list[GPS_observation_record class] , 所使用的观测站2观测文件记录
    br_records :  list[GPS_brdc_record class] , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    station1_coor : list , 观测站1坐标已知值
    station2_coor : list , 观测站2坐标已知值
    c : const , 光速(单位为m/s)
    """
    # 载波相位和伪距相位
    cp_band = bands[0]
    pr_band = bands[1]

    # 筛选出两个站点的观测记录
    station1_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station1_ob_records))
    station2_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station2_ob_records))

    # 选择相邻两个历元均存在的四颗卫星
    available_SVNs = []
    original_SVNS = []
    for station2_record in station2_ob_records:
        original_SVNS.append(station2_record.SVN)
        # 对station1_ob_record进行同一颗卫星的筛选
        station1_record_base = list(filter(lambda o: o.SVN == station2_record.SVN, station1_ob_records))
        if len(station1_record_base) != 1:
            continue
        else:
            if (observation_isnot_null(station1_record_base[0], bands) and observation_isnot_null(station2_record, bands)):
                available_SVNs.append(station2_record.SVN)
            else:
                continue

    print("available_SVNs:", available_SVNs)
    print("original_SVNS:", original_SVNS)

    # 初始地面点坐标
    X1, Y1, Z1 = station1_coor
    X2, Y2, Z2 = station2_coor
    # 载波的波长
    lamb = get_lamb_from_band(cp_band)

    # 先大致计算各卫星所在位置(注:必须在站的初始位置较靠近真实坐标时才有效)
    satellite_ele = {}
    Tr_GPSws = TimeSystem.GPSws(TimeSystem.from_datetime_cal_GPSws(Tr)[0], TimeSystem.from_datetime_cal_GPSws(Tr)[1])
    for SVN in available_SVNs:
        coorX_Tr, coorY_Tr, coorZ_Tr = SatellitePosition.cal_SatellitePosition_GPS_GPSws(Tr_GPSws, SVN, br_records)
        ele_sta1_Tr = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
        # ele_sta2_Tr = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
        # ele_total = ele_sta1_Tr + ele_sta2_Tr
        # satellite_ele[SVN] = ele_total/2 * 180 / math.pi
        satellite_ele[SVN] = ele_sta1_Tr / 2 * 180 / math.pi
    # 根据高度角选择最合适的基准卫星, 以及确定其他卫星
    the_SVN = max(zip(satellite_ele.values(), satellite_ele.keys()))[1]
    diff_SVNs = available_SVNs
    diff_SVNs.remove(the_SVN)
    if ele_manager:
        ele_manager.add_epoch_elevations(Tr, list(satellite_ele.values()), list(satellite_ele.keys()))


    final_SVNs = []

    # 初始化各观测值矩阵
    l1 = []
    l2 = []

    # 获取卫星1的两站观测记录
    station1_base_record = list(filter(lambda o: o.SVN == the_SVN, station1_ob_records))[0]
    station2_base_record = list(filter(lambda o: o.SVN == the_SVN, station2_ob_records))[0]

    for available_PRN in diff_SVNs:  # 卫星2

        """
        根据PRN对第一个历元两个站观测记录的的筛选
        """

        station1_record = list(filter(lambda o: o.SVN == available_PRN, station1_ob_records))[0]
        station2_record = list(filter(lambda o: o.SVN == available_PRN, station2_ob_records))[0]

        # 构造双差方程
        L1obs_sta1sat1 = station1_base_record.data[cp_band]['observation']
        L1obs_sta2sat1 = station2_base_record.data[cp_band]['observation']
        L1obs_sta1sat2 = station1_record.data[cp_band]['observation']
        L1obs_sta2sat2 = station2_record.data[cp_band]['observation']

        P1obs_sta1sat1 = station1_base_record.data[pr_band]['observation']
        P1obs_sta2sat1 = station2_base_record.data[pr_band]['observation']
        P1obs_sta1sat2 = station1_record.data[pr_band]['observation']
        P1obs_sta2sat2 = station2_record.data[pr_band]['observation']

        # 计算卫星发出信号时刻及发出信号时刻在ECEF坐标系中的位置，以及信号发射时刻站星距离
        # 站1到卫星1
        ts_sta1sat1_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station1_base_record.data[pr_band]['observation'], br_records, doCRC=True)
        coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat1_Tr1, the_SVN, br_records)
        dt_sta1sat1_Tr1 = station1_base_record.data[pr_band]['observation'] / c
        # dt_sta1sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat1_Tr1.GpsSecond
        Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1], dt_sta1sat1_Tr1)
        lou_sta1sat1_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1])
        # lou_sta1sat1_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1])
        ele = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1])[0]
        if cutoff != 15.12345678:
            if ele < cutoff:
                continue

        # 站2到卫星1
        ts_sta2sat1_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station2_base_record.data[pr_band]['observation'], br_records, doCRC=True)
        coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat1_Tr1, the_SVN, br_records)
        dt_sta2sat1_Tr1 = station2_base_record.data[pr_band]['observation'] / c
        # dt_sta2sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat1_Tr1.GpsSecond
        Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1], dt_sta2sat1_Tr1)
        lou_sta2sat1_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1])
        # lou_sta2sat1_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2],[coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1])
        ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1])[0]
        if cutoff != 15.12345678:
            if ele < cutoff:
                continue

        # 站1到卫星2
        ts_sta1sat2_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station1_record.data[pr_band]['observation'], br_records, doCRC=True)
        coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat2_Tr1, available_PRN, br_records)
        dt_sta1sat2_Tr1 = station1_record.data[pr_band]['observation']/c
        # dt_sta1sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat2_Tr1.GpsSecond
        Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1], dt_sta1sat2_Tr1)
        lou_sta1sat2_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1])
        # lou_sta1sat2_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1])
        ele =CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1])[0]
        if cutoff != 15.12345678:
            if ele < cutoff:
                continue

        # 站2到卫星2
        ts_sta2sat2_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station2_record.data[pr_band]['observation'], br_records, doCRC=True)
        coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat2_Tr1, available_PRN, br_records)
        dt_sta2sat2_Tr1 = station2_record.data[pr_band]['observation']/c
        # dt_sta2sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat2_Tr1.GpsSecond
        Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1], dt_sta2sat2_Tr1)
        lou_sta2sat2_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1])
        # lou_sta2sat2_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1])
        ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1])[0]
        if cutoff != 15.12345678:
            if ele < cutoff:
                continue

        # 符合高度角要求则加入
        final_SVNs.append(available_PRN)

        # 构造相位部分常数阵
        l_part1 = lamb * (L1obs_sta2sat2 - L1obs_sta1sat2 - L1obs_sta2sat1 + L1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10
        l1.append(l_part1)

        l_part2 = (P1obs_sta2sat2 - P1obs_sta1sat2 - P1obs_sta2sat1 + P1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10
        l2.append(l_part2)

        # prnoise_manager.add_epoch_obsnoise(Tr, "1", the_SVN, P1obs_sta1sat1 - lou_sta1sat1_Tr10)
        # prnoise_manager.add_epoch_obsnoise(Tr, "2", the_SVN, P1obs_sta2sat1 - lou_sta2sat1_Tr10)
        # prnoise_manager.add_epoch_obsnoise(Tr, "1", available_PRN, P1obs_sta1sat2 - lou_sta1sat2_Tr10)
        # prnoise_manager.add_epoch_obsnoise(Tr, "2", available_PRN, P1obs_sta2sat2 - lou_sta2sat2_Tr10)

    DDobs_residual_manager.add_epoch_residuals(Tr, the_SVN, final_SVNs, l2)

    print("final_SVNs", final_SVNs)

    # 构造系数阵
    A = []
    for i in range(len(l1)):
        N_DD = make_Ambiguity_coefficient_matrix_row(i, len(l1), lamb)
        A.append(N_DD)

    # 构造权阵并求解
    Ps1 = np.linalg.inv(get_DD_Qmatrix(len(l1), 0.05))     # 相位
    Pz = Ps1

    A = np.array(A)
    l = np.array(l1)
    # l = np.array(l1)-np.array(l2)

    # 解算
    # x = np.linalg.inv(A.T @ Pz @ A) @ (A.T @ Pz @ l)
    x = np.linalg.inv(A) @ l
    Q = np.linalg.inv(A.T @ Pz @ A).astype(float)
    V = A @ x - l

    # 更新参数
    N_float = x

    if DDambiguity_manager:
        if DDambiguity_manager.round:
            DDambiguity_manager.add_epoch_ambiguity(Tr, the_SVN, diff_SVNs, np.round(N_float))
        else:
            DDambiguity_manager.add_epoch_ambiguity(Tr, the_SVN, diff_SVNs, N_float)


    return N_float, V, the_SVN, final_SVNs




# 基于载波相位+伪距的双差，单历元 (其中一个观测站为已知坐标站点)，并且考虑电离层误差
def DD_onCarrierPhase_and_Pseudorange_withIono_1known(station1_ob_records, station2_ob_records, br_records,
                                             Tr, station1_init_coor, station2_init_coor, CRC=True, cutoff=15.12345678,
                                             c=299792458, ambi_fix=True):
    """
    station1_ob_records : list[GPS_observation_record class] , 所使用的观测站1观测文件记录
    station2_ob_records : list[GPS_observation_record class] , 所使用的观测站2观测文件记录
    br_records :  list[GPS_brdc_record class] , 所使用的卫星广播星历记录
    Tr : datetime.datetime , 接收机接收到信号的时刻,GPS时刻
    station1_init_coor : list , 观测站1坐标已知值
    CRC : bool , 是否进行相对论钟差改正
    c : const , 光速(单位为m/s)
    ambi_fix : bool , 是否进行模糊度固定
    station2_init_coor : list , 观测站2坐标初值
    """
    # 筛选出两个站点的观测记录
    station1_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station1_ob_records))
    station2_ob_records = list(
        filter(lambda o: o.SVN[0] == "G" and o.time == Tr and o.data != "", station2_ob_records))

    # 选择相邻两个历元均存在的四颗卫星
    available_SVNs = []
    original_SVNS = []
    for station2_record in station2_ob_records:
        original_SVNS.append(station2_record.SVN)
        # 对station1_ob_record进行同一颗卫星的筛选
        station1_record_base = list(filter(lambda o: o.SVN == station2_record.SVN, station1_ob_records))
        if len(station1_record_base) != 1:
            continue
        else:
            if (observation_isnot_null(station1_record_base[0]) and observation_isnot_null(station2_record)):
                available_SVNs.append(station2_record.SVN)
            else:
                continue

    # 判断卫星数是否足够
    num_flag = True
    print("all satellite:", original_SVNS)
    print("the abled satellite:", available_SVNs)
    ob_num = len(available_SVNs)
    if ob_num < 5:
        num_flag = False
    elif ob_num >= 5:
        num_flag = True

    # 卫星数足够，则开始迭代进行双差观测的平差求解
    # if num_flag == False:
    #     return
    if num_flag:
        # 初始地面点坐标
        X1, Y1, Z1 = station1_init_coor
        X2, Y2, Z2 = station2_init_coor
        Qcoor = 0
        # 载波的波长
        lamb = lamb_L1
        # 平差迭代次数计数
        no = 0

        # 先大致计算各卫星所在位置(注:必须在站的初始位置较靠近真实坐标时才有效)
        satellite_ele = {}
        Tr_GPSws = TimeSystem.GPSws(TimeSystem.from_datetime_cal_GPSws(Tr)[0], TimeSystem.from_datetime_cal_GPSws(Tr)[1])
        for SVN in available_SVNs:
            coorX_Tr, coorY_Tr, coorZ_Tr = SatellitePosition.cal_SatellitePosition_GPS_GPSws(Tr_GPSws, SVN, br_records)
            ele_sta1_Tr = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
            ele_sta2_Tr = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_Tr, coorY_Tr, coorZ_Tr])[0]
            ele_total = ele_sta1_Tr + ele_sta2_Tr
            satellite_ele[SVN] = ele_total
        # 根据高度角选择最合适的基准卫星, 以及确定其他卫星
        the_SVN = max(zip(satellite_ele.values(), satellite_ele.keys()))[1]
        diff_SVNs = available_SVNs
        diff_SVNs.remove(the_SVN)

        while True:
            # 如果超出平差迭代求解超出8次则跳出
            if no > 8:
                break
            no += 1
            final_SVNs = []

            # 初始化各观测值矩阵
            A1 = []
            l1 = []
            A2 = []
            l2 = []

            # 获取卫星1的两站观测记录
            station1_base_record = list(filter(lambda o: o.SVN == the_SVN, station1_ob_records))[0]
            station2_base_record = list(filter(lambda o: o.SVN == the_SVN, station2_ob_records))[0]

            for available_PRN in diff_SVNs:  # 卫星2

                """
                根据PRN对第一个历元两个站观测记录的的筛选
                """

                station1_record = list(filter(lambda o: o.SVN == available_PRN, station1_ob_records))[0]
                station2_record = list(filter(lambda o: o.SVN == available_PRN, station2_ob_records))[0]

                # 构造双差方程
                L1obs_sta1sat1 = station1_base_record.data['L1']['observation']
                L1obs_sta2sat1 = station2_base_record.data['L1']['observation']
                L1obs_sta1sat2 = station1_record.data['L1']['observation']
                L1obs_sta2sat2 = station2_record.data['L1']['observation']

                P1obs_sta1sat1 = station1_base_record.data['P2']['observation']
                P1obs_sta2sat1 = station2_base_record.data['P2']['observation']
                P1obs_sta1sat2 = station1_record.data['P2']['observation']
                P1obs_sta2sat2 = station2_record.data['P2']['observation']

                # 计算卫星发出信号时刻及发出信号时刻在ECEF坐标系中的位置，以及信号发射时刻站星距离
                # 站1到卫星1
                ts_sta1sat1_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station1_base_record.data['P2']['observation'], br_records, doCRC=True)
                coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat1_Tr1, the_SVN, br_records)
                #dt_sta1sat1_Tr1 = station1_base_record.data['P2']['observation'] / c
                dt_sta1sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat1_Tr1.GpsSecond
                Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1], dt_sta1sat1_Tr1)
                lou_sta1sat1_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat1_Tr1, Yeci_sta1sat1_Tr1, Zeci_sta1sat1_Tr1])
                ele = CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat1_Tr1, coorY_sta1sat1_Tr1, coorZ_sta1sat1_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站2到卫星1
                ts_sta2sat1_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, the_SVN, station2_base_record.data['P2']['observation'], br_records, doCRC=True)
                coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat1_Tr1, the_SVN, br_records)
                # dt_sta2sat1_Tr1 = station2_base_record.data['P2']['observation'] / c
                dt_sta2sat1_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat1_Tr1.GpsSecond
                Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1], dt_sta2sat1_Tr1)
                lou_sta2sat1_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat1_Tr1, Yeci_sta2sat1_Tr1, Zeci_sta2sat1_Tr1])
                ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat1_Tr1, coorY_sta2sat1_Tr1, coorZ_sta2sat1_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站1到卫星2
                ts_sta1sat2_Tr1, dts_sta1_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station1_record.data['P2']['observation'], br_records, doCRC=True)
                coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta1sat2_Tr1, available_PRN, br_records)
                # dt_sta1sat2_Tr1 = station1_record.data['P2']['observation']/c
                dt_sta1sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta1sat2_Tr1.GpsSecond
                Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1], dt_sta1sat2_Tr1)
                lou_sta1sat2_Tr10 = CoorTransform.cal_distance([X1, Y1, Z1], [Xeci_sta1sat2_Tr1, Yeci_sta1sat2_Tr1, Zeci_sta1sat2_Tr1])
                ele =CoorTransform.cal_ele_and_A([X1, Y1, Z1], [coorX_sta1sat2_Tr1, coorY_sta1sat2_Tr1, coorZ_sta1sat2_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                # 站2到卫星2
                ts_sta2sat2_Tr1, dts_sta2_Tr1 = SPP.cal_EmitTime_from_datetime(Tr, available_PRN, station2_record.data['P2']['observation'], br_records, doCRC=True)
                coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1 = SatellitePosition.cal_SatellitePosition_GPS_GPSws(ts_sta2sat2_Tr1, available_PRN, br_records)
                # dt_sta2sat2_Tr1 = station2_record.data['P2']['observation']/c
                dt_sta2sat2_Tr1 = Tr_GPSws.GpsSecond - ts_sta2sat2_Tr1.GpsSecond
                Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1 = CoorTransform.earth_rotation_correction([coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1], dt_sta2sat2_Tr1)
                lou_sta2sat2_Tr10 = CoorTransform.cal_distance([X2, Y2, Z2], [Xeci_sta2sat2_Tr1, Yeci_sta2sat2_Tr1, Zeci_sta2sat2_Tr1])
                ele = CoorTransform.cal_ele_and_A([X2, Y2, Z2], [coorX_sta2sat2_Tr1, coorY_sta2sat2_Tr1, coorZ_sta2sat2_Tr1])[0]
                if cutoff != 15.12345678:
                    if ele * 180 / math.pi < cutoff:
                        continue

                final_SVNs.append(available_PRN)

                """
                  构造矩阵阵
                """
                # 构造相位部分系数阵和常数阵
                a_sta2_X = (X2 - Xeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (X2 - Xeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                a_sta2_Y = (Y2 - Yeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (Y2 - Yeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                a_sta2_Z = (Z2 - Zeci_sta2sat2_Tr1) / lou_sta2sat2_Tr10 - (Z2 - Zeci_sta2sat1_Tr1) / lou_sta2sat1_Tr10
                A_part1 = [a_sta2_X, a_sta2_Y, a_sta2_Z, -1]     # 最后一个系数为相位电离层延迟系数
                l_part1 = lamb * (L1obs_sta2sat2 - L1obs_sta1sat2 - L1obs_sta2sat1 + L1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10

                # 构造伪距部分系数阵和常数阵
                A_part2 = [a_sta2_X, a_sta2_Y, a_sta2_Z, 1]      # 最后一个系数为伪距电离层延迟系数
                # 构造常数阵
                l_part2 = (P1obs_sta2sat2 - P1obs_sta1sat2 - P1obs_sta2sat1 + P1obs_sta1sat1) - lou_sta2sat2_Tr10 + lou_sta2sat1_Tr10 + lou_sta1sat2_Tr10 - lou_sta1sat1_Tr10

                # 如果两个历元均符合要求，则加入各历元对应的矩阵中
                A1.append(A_part1)
                l1.append(l_part1)
                A2.append(A_part2)
                l2.append(l_part2)

            qualitified_num = len(l1) + len(l2)
            if qualitified_num < 5:
                qualitified_flag = False
            elif qualitified_num >= 5:
                qualitified_flag = True

            if not qualitified_flag:
                X2, Y2, Z2 = station2_init_coor
                Qcoor = 10000
                break

            # 构造系数阵
            A = []
            for i in range(len(l1)):
                N_DD = make_Ambiguity_coefficient_matrix_row(i, len(l1), lamb)
                A.append(A1[i]+N_DD)
            for i in range(len(l2)):
                N_DD = [0 for i in range(len(l2))]
                A.append(A2[i]+N_DD)

            # 构造权阵并求解
            Ps1 = get_DD_Pmatrix(len(l1), 1000)
            Ps2 = get_DD_Pmatrix(len(l2), 1)
            Pz = diagonalize_squarematrix(Ps1, Ps2)
            A = np.array(A)
            l = np.array(l1 + l2)

            # 改正数发散太过严重则不再继续平差
            if abs(max(l.tolist())) > 1e10:
                break
            x = np.linalg.inv(A.T @ Pz @ A) @ (A.T @ Pz @ l)
            Q = np.linalg.inv(A.T @ Pz @ A).astype(float)
            Qcoor = Q[:3, :3]

            # 更新参数
            dX2 = x[0]
            dY2 = x[1]
            dZ2 = x[2]
            Idelay = x[3]
            N_float = x[4:]
            X2 += dX2
            Y2 += dY2
            Z2 += dZ2
            print(no, ": ", len(Pz)/2, "组 多余观测：", len(Pz)/2-3, [dX2, dY2, dZ2, N_float])
            print("    differenced satellite:", final_SVNs)
            # 判断迭代停止条件
            if abs(dX2) < 1e-4 and abs(dY2) < 1e-4 and abs(dZ2) < 1e-4:
                break

        # 进行模糊度固定
        if ambi_fix and qualitified_flag:
            # 调用LAMBDA方法进行整数估计
            Qaa = get_symmetric_matrix(Q[4:, 4:])
            Qba = Q[:3, 4:]
            N_fixed, sqnorm, Ps, Qzhat, Z, nfixed, mu = LAMBDA.main(N_float, Qaa)
            # 更新参数估计
            b_hat = np.array([X2, Y2, Z2])
            a_hat = N_float
            Coor = MAPmethod(b_hat, a_hat, Qaa, Qba, N_fixed[:, 0])
            X2, Y2, Z2 = Coor
            # todo 计算MAP计算后的坐标方差
        else:
            Coor = [X2, Y2, Z2]

    # 如果没有足够的卫星
    else:
        X2 ,Y2, Z2 = station2_init_coor
        Qcoor = 10000


    return [X2, Y2, Z2], Qcoor


if __name__ == "__main__":
    # station2_observation_file = r"edata\obs\ptbb3100.20o"
    # station1_observation_file = r"edata\obs\leij3100.20o"    # 已知站点 leij
    station1_observation_file = r"edata\obs\zim23100.20o"
    # station1_observation_file = r"edata\obs\wab23100.20o"    # 已知站点 wab2
    station2_observation_file = r"edata\obs\zimm3100.20o"  # 已知站点 zimm
    broadcast_file = r"edata\sat_obit\brdc3100.20n"
    # 读入观测文件内容,得到类型对象列表
    knownStation_ob_records = DoFile.read_Rinex2_oFile(station1_observation_file)
    unknownStation_ob_records = DoFile.read_Rinex2_oFile(station2_observation_file)
    br_records = DoFile.read_GPS_nFile(broadcast_file)
    print("数据读取完毕！")
    Tr = datetime.datetime(2020, 11, 5, 0, 0, 0)
    # init_coor = [3658785.6000, 784471.1000, 5147870.7000]
    init_coor = [4331297.3480, 567555.6390, 4633133.7280]      # zimm
    # init_coor = [4331300.1600, 567537.0810, 4633133.5100]  # zim2
    # init_coor = SPP.SPP_on_GPS_broadcastrecords(unknownStation_ob_records, br_records, Tr+datetime.timedelta(seconds=60))[0:3]
    # init_coor = [0, 0, 0]
    # knownStation_coor = [0.389873613453103E+07, 0.855345521080705E+06, 0.495837257579542E+07]  # leij
    # knownStation_coor = [4327318.2325, 566955.9585, 4636425.9246]  # wab2
    knownStation_coor = [4331300.1600, 567537.0810, 4633133.5100]  # zim2
    # knownStation_coor = [4331297.3480, 567555.6390, 4633133.7280]  # zimm
    true_coors = []
    cal_coors = []
    while Tr < datetime.datetime(2020, 11, 5, 1, 0, 0):
        print(Tr.hour, Tr.minute, Tr.second)
        CoorXYZ, Q, N_float, the_SVN, final_SVNs, Pse, v= DD_onCarrierPhase_and_Pseudorange_1known(knownStation_ob_records, unknownStation_ob_records, br_records, Tr,
                                      knownStation_coor, init_coor, ambi_fix=True)
        Xk, Yk, Zk = CoorXYZ
        cal_coors.append([Xk, Yk, Zk])
        # true_coors.append([0.365878555276965E+07, 0.784471127238666E+06, 0.514787071062059E+07])  # warn
        # true_coors.append([3844059.7545, 709661.5334, 5023129.6933])     # ptbb
        true_coors.append([4331297.3480, 567555.6390, 4633133.7280])      # zimm
        # true_coors.append([4331300.1600, 567537.0810, 4633133.5100])  # zim2
        # true_coors.append([0.389873613453103E+07,0.855345521080705E+06,0.495837257579542E+07])   #leij
        # true_coors.append([-0.267442768572702E+07,0.375714305701559E+07,0.439152148514515E+07])  #chan
        Tr += datetime.timedelta(seconds=30)
    SPP.cal_NEUerrors(true_coors, cal_coors)
    SPP.cal_XYZerrors(true_coors, cal_coors)
    SPP.cal_Coorerrors(true_coors, cal_coors)
    print("neu各方向RMSE:", ResultAnalyse.get_NEU_rmse(true_coors, cal_coors))
    print("坐标RMSE:", ResultAnalyse.get_coor_rmse(true_coors, cal_coors))