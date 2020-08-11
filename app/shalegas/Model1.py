
"""

Notes
-----

    1. 混合物的摩尔浓度 c 的计算公式为
        c = p/(ZRT), 
        Z^3 - (1 - B)Z^2 + (A - 3B^2 -2B)Z - (AB - B^2 -B^3) = 0
        A = a p/(R^2T^2)
        B = b p/(RT)
        其中:

        a = 3
        b = 1/3

        p 是压力 
        Z 是压缩系数 
        R 是气体常数
        T 是温度
        M_i 是组分 i 的摩尔质量
        
        混合物的密度计算公式为:

        rho = M_0 c_0 + M_1 c_1 + M_2 c_2 ...

    2. c_i : 组分 i 的摩尔浓度
       z_i : 组分 i 的摩尔分数

       c_i = z_i c

    3. 
    甲烷: methane,  CH_4,   16.04 g/mol,  0.42262 g/cm^3
    乙烷: Ethane, C_2H_6,   30.07 g/mol, 1.212 kg/m^3
    丙烷: Propane,  C_3H_8,  44.096 g/mol,  1.83 kg/m^3 
    (25度 100 kPa

    4. 气体常数  R = 8.31446261815324 	J/K/mol

    5. 6.02214076 x 10^{23}


References
----------
[1] https://www.sciencedirect.com/science/article/abs/pii/S0378381217301851

Authors
    Huayi Wei, weihuayi@xtu.edu.cn
"""
import numpy as np
from scipy.sparse import coo_matrix
from fealpy.mesh import MeshFactory
from fealpy.functionspace import RaviartThomasFiniteElementSpace2d
from fealpy.functionspace import ScaledMonomialSpace2d
from fealpy.timeintegratoralg.timeline import UniformTimeLine

import vtk
import vtk.util.numpy_support as vnp

class Model_1():
    def __init__(self):
        self.m = [0.01604, 0.03007, 0.044096] # kg/mol 一摩尔质量, TODO：确认是 g/mol
        self.R = 8.31446261815324 # J/K/mol
        self.T = 397 # K 绝对温度

    def init_pressure(self, pspace):
        """

        Notes
        ----
        目前压力用分片常数逼近。
        """
        ph = pspace.function()
        ph[:] = 50 # 初始压力
        return ph

    def init_molar_density(self, cspace, ph):
        c = self.mixed_molar_dentsity(ph)
        ch = cspace.function(dim=3)
        ch[:, 2] = c 
        return ch

    def space_mesh(self, n=50):
        box = [0, 50, 0, 50]
        mf = MeshFactory()
        mesh = mf.boxmesh2d(box, nx=n, ny=n, meshtype='tri')
        return mesh

    def time_mesh(self, n=100):
        timeline = UniformTimeLine(0, 0.1, n)
        return timeline

    def mixed_molar_dentsity(self, ph):
        """

        Notes
        ----
        给一个分片常数的压力，计算混合物的浓度 c
        """
        NC = len(ph)
        t = self.R*self.T 
        A = 3*p/t**2
        B = p/t/3 
        
        a = np.ones((NC, 4), dtype=ph.dtype)
        a[:, 1] = B - 1
        a[:, 2] = A - 3*B**2 - 2*B
        a[:, 3] = -A*B + B**2 - B**3
        Z = np.max(np.array(list(map(np.roots, a))), axis=-1)
        c = p/Z/t 
        return c

    @cartesian
    def velocity_bc(self, p, n):
        x = p[..., 0]
        y = p[..., 1]
        z = p[..., 2]
        val = np.zeros(p.shape[:-1], dtype=np.float64)
        flag0 = (x < 1) & (y < 1)
        val[flag0] = -0.1
        flag1 = (x > 0.9) & (y > 0.9)
        val[flag1] = 0.1 
        return val

    @cartesian
    def pressure_bc(self, p):
        x = p[..., 0]
        y = p[..., 1]
        z = p[..., 2]
        val = np.zeros(p.shape[:-1], dtype=np.float64)
        flag0 = (x < 1) & (y < 1)
        val[flag0] = 100 
        flag1 = (x > 0.9) & (y > 0.9)
        val[flag1] = 25 
        return val

class ShaleGasSolver():
    def __init__(self, model):
        self.model = model
        self.mesh = model.space_mesh()
        self.timeline =  model.time_mesh() 
        self.uspace = RaviartThomasFiniteElementSpace2d(self.mesh, p=0)
        self.cspace = ScaledMonomialSpace2d(self.mesh, p=1) # 线性间断有限元空间

        self.uh = self.uspace.function() # 速度
        self.ph = model.init_pressure(self.uspace.smspace) # 初始压力

        # 三个组分的摩尔密度, 三个组分一起计算 
        self.ch = model.init_molar_density(self.cspace, self.ph) 

        # TODO：初始化三种物质的浓度
        self.options = {
                'viscosity': 1.0,    # 粘性系数
                'permeability': 1.0, # 渗透率 
                'temperature': 397, # 初始温度 K
                'pressure': 50,   # 初始压力
                'porosity': 0.2,  # 孔隙度
                'injecttion_rate': 0.1,  # 注入速率
                'compressibility': 0.001, #压缩率
                'pmv': (1.0, 1.0, 1.0)} # 偏摩尔体积
        self.CM = self.cspace.cell_mass_matrix() 
        self.H = inv(self.CM)

        c = self.options['viscosity']/self.options['permeability']
        self.M = c*self.uspace.mass_matrix()
        self.B = -self.uspace.div_matrix()

        dt = self.timeline.dt
        c = self.options['porosity']*self.options['compressibility']/dt
        self.D = c*self.uspace.smspace.mass_matrix() 

        # vtk 文件输出
        node, cell, cellType, NC = self.mesh.to_vtk()
        self.points = vtk.vtkPoints()
        self.points.SetData(vnp.numpy_to_vtk(node))
        self.cells = vtk.vtkCellArray()
        self.cells.SetCells(NC, vnp.numpy_to_vtkIdTypeArray(cell))
        self.cellType = cellType

    def one_step_solve():
        """

        Notes
        -----
            求解一个时间层的数值解
        """
        udof = self.uspace.number_of_global_dofs()
        pdof = self.uspace.smspace.number_of_global_dofs()
        cdof = self.cspace.number_of_global_dofs()

        timeline = self.timeline
        phi = self.options['porosity'] # 孔隙度
        dt = timeline.current_time_step_length()
        nt = timeline.next_time_level()

        # 1. 求解下一层速度和压力
        M = self.M
        B = self.B
        D = self.D
        E = self.uspace.pressure_matrix(self.ch)

        F1 = D@self.ph

        AA = bmat([[M, B], [E, D]], format='csr')
        FF = np.r_['0', np.zeros(udof), F1]
        x = spsolve(AA, FF).reshape(-1)
        self.uh[:] = x[:udof]
        self.ph[:] = x[udof:]

        # 2. 求解下一层的浓度

        nc = len(self.ch.shape[1])
        for i in range(nc):
            F = self.uspace.convection_vector(nt, self.ch.index(i), self.uh,
                    g=model.dirichlet) 
            F = self.H@(F[:, :, None]/phi)
            F *= dt
            self.ch[:, i] += F.flat

    def solve(self):
        """

        Notes
        -----

        计算所有的时间层。
        """

        rdir = self.options['rdir']
        step = self.options['step']
        timeline = self.timeline
        dt = timeline.current_time_step_length()
        timeline.reset() # 时间置零

        fname = rdir + '/test_'+ str(timeline.current).zfill(10) + '.vtu'
        self.write_to_vtk(fname)
        print(fname)
        while not timeline.stop():
            self.one_step_solve()
            timeline.current += 1
            if timeline.current%step == 0:
                fname = rdir + '/test_'+ str(timeline.current).zfill(10) + '.vtu'
                print(fname)
                self.write_to_vtk(fname)
        timeline.reset()

    def write_to_vtk(self, fname):
        # 重心处的值
        bc = np.array([1/3, 1/3, 1/3], dtype=np.float64)
        ps = self.mesh.bc_to_point(bc)
        vmesh = vtk.vtkUnstructuredGrid()
        vmesh.SetPoints(self.points)
        vmesh.SetCells(self.cellType, self.cells)
        cdata = vmesh.GetCellData()
        pdata = vmesh.GetPointData()

        uh = self.uh 
        ph = self.ph

        V = uh.value(bc)
        val = vnp.numpy_to_vtk(V)
        val.SetName('velocity')
        cdata.AddArray(val)

        P = ph.value(bc)
        val = vnp.numpy_to_vtk(V)
        val.SetName('velocity')
        cdata.AddArray(val)

        ch = self.ch
        val = ch.value(ps)
        if len(ch.shape) == 2:
            for i in range(ch.shape[1]):
                val = vnp.numpy_to_vtk(val:, i])
                val.SetName('concentration' + str(i))
                cdata.AddArray(val)

        writer = vtk.vtkXMLUnstructuredGridWriter()
        writer.SetFileName(fname)
        writer.SetInputData(vmesh)
        writer.Write()



if __name__ == '__main__':
    import matplotlib.pyplot as plt

    model = Model_1()

    solver = ShaleGasSolver(model)

    mesh = solver.mesh

    fig = plt.figure()
    axes = fig.gca()
    mesh.add_plot(axes)
    plt.show()
