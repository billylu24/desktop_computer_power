#!/usr/bin/ruby

require 'optparse'

class SMU
  # from zenstates
  SMU_MSG_TransferTableToDram = 0x3
  SMU_MSG_GetDramBaseAddress = 0x4
  SMU_MSG_GetTableVersion = 0x5
  SMU_MSG_EnableOcMode = 0x5D
  SMU_MSG_DisableOcMode = 0x5E
  SMU_MSG_SetOverclockFrequencyAllCores = 0x5F
  SMU_MSG_SetOverclockFrequencyPerCore = 0x60
  SMU_MSG_SetOverclockCpuVid = 0x61
  SMU_MSG_SetPPTLimit = 0x56
  SMU_MSG_SetTDCVDDLimit = 0x57
  SMU_MSG_SetEDCVDDLimit = 0x58
  SMU_MSG_SetHTCLimit = 0x59
  SMU_MSG_SetPBOScalar = 0x5B
  SMU_MSG_GetPBOScalar = 0x6D
  SMU_MSG_SetDldoPsmMargin = 0x6
  SMU_MSG_SetAllDldoPsmMargin = 0x7
  SMU_MSG_GetDldoPsmMargin = 0xD5
  SMU_MSG_GetLN2Mode = 0xDD

  def self.get(op, arg = nil)
    bin_op = [op].pack("l<")
    bin_arg = arg ? [arg, 0, 0, 0, 0, 0].pack("l<*") : nil

    File.binwrite("/sys/kernel/ryzen_smu_drv/smu_args", bin_arg) if bin_arg
    File.binwrite("/sys/kernel/ryzen_smu_drv/rsmu_cmd", bin_op)
    result = File.binread("/sys/kernel/ryzen_smu_drv/smu_args").unpack("l<*")
    result.first
  end

  def self.set(op, value)
    bin_op =[op].pack("l<")
    bin_value =[value, 0, 0, 0, 0, 0].pack("l<*")
                                                      
    File.binwrite("/sys/kernel/ryzen_smu_drv/smu_args", bin_value)
    File.binwrite("/sys/kernel/ryzen_smu_drv/rsmu_cmd", bin_op)
    nil
  end
  
end

class PM
TABLE_MAPPING = {
  2 => "PPT_LIMIT",
  3 => "PPT_VALUE",
  8 => "TDC_LIMIT",
  9 => "TDC_VALUE",
  10 => "THM_LIMIT",
  11 => "THM_VALUE",
  26 => "CPU_POWER",
  41 => "CPU_VOLTAGE",
  52 => "SOC_VOLTAGE",
  #56 => "MISC",
  61 => "EDC_LIMIT",
  62 => "EDC_VALUE",
  70 => "FCLK",
  74 => "UCLK",
  78 => "MCLK",
  268 => "VDDP",
  #544 => "CCD1L3Temp",
  #545 => "CCD2L3Temp",  
  #0x118/4 => "FCLK",
  #0x128/4 => "UCLK",
  #0x138/4 => "MCLK",
  #0xD0/4 => "SOC",
  #0x430/4 => "VDDP",
}

  def initialize

  end

  def update
    @table = File.binread("/sys/kernel/ryzen_smu_drv/pm_table").unpack("e*")
  end
  
  def dump
    puts "IDX | VALUE"
    @table.each_with_index do |entry, idx|
      puts "#{"%.3d" % idx} | #{entry.round(1)}}"
    end
  end

  def monitor
    @table.each_with_index do |v,i|
      if TABLE_MAPPING[i]
        puts "#{i}(#{TABLE_MAPPING[i]}): #{v.round(2)}"
      else
        #puts "#{i}: #{v.round(2)}"
      end
    end
  end
end

options = {}
OptionParser.new do |opts|
  opts.banner = "Usage: ryzen4_ctl.rb [--verbose] [other options]"

  @verbose = false
  
  opts.on("--verbose", "verbose") do |v|
    @verbose = true
  end
    
  opts.on("--pm-version", "PM table version") do |v|
    puts SMU.get(SMU::SMU_MSG_GetTableVersion)
  end
  
  opts.on("--pm-monitor", "PM table monitor") do |v|
    pm = PM.new
    pm.update
    pm.monitor
  end

   opts.on("--pm-dump", "PM table full dump") do |v|
    pm = PM.new
    pm.update
    pm.dump
   end
    
  opts.on("--set-ppt-limit PPT", "set PPT limit (W)") do |v|
    ppt = v.to_i
    if ppt.between?(20, 300)
      SMU.set(SMU::SMU_MSG_SetPPTLimit,ppt*1000)
      puts "Set PPT limit to #{ppt}W" if @verbose
    end
  end

  opts.on("--set-tdc-limit TDC", "set TDC limit (A)") do |v|
    tdc = v.to_i
    if tdc.between(20, 200)
      SMU.set(SMU::SMU_MSG_SetTDCVDDLimit,tdc*1000)
      puts "Set TDC limit to #{tdc}A" if @verbose
    end
  end

  opts.on("--set-edc-limit EDC", "set EDC limit (A)") do |v|
    edc = v.to_i
    if edc.between(20, 300)
      SMU.set(SMU::SMU_MSG_SetEDCVDDLimit,edc*1000)
      puts "Set EDC limit to #{edc}A" if @verbose
    end
  end

    opts.on("--set-therm-limit TEMP", "set thermal limit (C)") do |v|
    temp = v.to_i
    if temp.between?(20, 100)
      SMU.set(SMU::SMU_MSG_SetHTCLimit,temp)
      puts "Set thermal limit to #{temp}C" if @verbose
    end
  end

# 65W PPT: 88, TDC: 75, EDC: 150
# 105W PPT: 142, TDC: 110, EDC: 170
# 170W PPT: 230, TDC: 160, EDC: 225

    opts.on("--set-eco-mode MODE", "set eco mode (65,105,170)") do |v|
      eco = v.to_i

      case eco
      when 65
        SMU.set(SMU::SMU_MSG_SetPPTLimit,88000)
        SMU.set(SMU::SMU_MSG_SetTDCVDDLimit,75000)
        SMU.set(SMU::SMU_MSG_SetEDCVDDLimit,150000)
        puts "Set Eco mode #{eco}W" if @verbose
      when 105
        SMU.set(SMU::SMU_MSG_SetPPTLimit,142000)
        SMU.set(SMU::SMU_MSG_SetTDCVDDLimit,110000)
        SMU.set(SMU::SMU_MSG_SetEDCVDDLimit,170000)
        puts "Set Eco mode #{eco}W" if @verbose
      when 170
        SMU.set(SMU::SMU_MSG_SetPPTLimit,230000)
        SMU.set(SMU::SMU_MSG_SetTDCVDDLimit,160000)
        SMU.set(SMU::SMU_MSG_SetEDCVDDLimit,225000)
        puts "Set Eco mode #{eco}W" if @verbose
      end
  end
    
  opts.on("--set-co CO", "set curve optimizer") do |v|
    co = v.to_i
    if co.between?(-30, 30)
      SMU.set(SMU::SMU_MSG_SetAllDldoPsmMargin,co)
      puts "Set curve optimizer to #{co}" if @verbose
    end
  end

  opts.on("--get-co", "get current curve optimizer") do |v|
    puts SMU.get(SMU::SMU_MSG_GetDldoPsmMargin, 0)
  end
end.parse!


