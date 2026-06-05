# -*- coding: utf-8 -*-
"""第1题（基础题，30分）：RPC 正解。

给定 RPC 模型与一组地面点，正解投影到像方得到像点(line, sample)，
与老师参考答案 standard_answer_pixels.csv 对比（行列号，左上像素中心为原点）。
"""
import os
import numpy as np
from rpc import RPCModel
import suite_paths as sp

OUT = sp.out_dir()
os.makedirs(OUT, exist_ok=True)


def main():
    gp_path = sp.ground_points_csv()
    if gp_path is None:
        print("跳过 Q1 RPC 正解：未在界面指定地面检核点 CSV")
        return
    img = sp.images()[0]
    rpc_path, _ = sp.image_paths(img)
    rpc = RPCModel(str(rpc_path))
    gp = np.loadtxt(str(gp_path), delimiter=",", skiprows=1)
    ids, lon, lat, h = gp[:, 0], gp[:, 1], gp[:, 2], gp[:, 3]

    line, samp = rpc.forward(lat, lon, h)

    out_csv = os.path.join(OUT, "q1_pixels.csv")
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("id,line,sample\n")
        for i in range(len(ids)):
            f.write(f"{int(ids[i])},{line[i]:.6f},{samp[i]:.6f}\n")

    print(f"Q1 正解完成 {len(ids)} 点 → {out_csv}")


if __name__ == "__main__":
    main()
