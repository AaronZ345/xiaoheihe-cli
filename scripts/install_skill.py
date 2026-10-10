from xhh_operator.skill_install import install_skill

if __name__ == "__main__":
    result = install_skill()
    print("已安装 " + result["skill"] + " 技能。")
