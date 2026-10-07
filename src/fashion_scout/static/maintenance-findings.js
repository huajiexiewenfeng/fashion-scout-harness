const reasons={IMAGE_NOT_ARCHIVED:'图片尚未保存在本机',IMAGE_SCOPE_UNKNOWN:'尚不能确定图片范围',ENUMERATION_UNKNOWN:'图片枚举范围尚未确认',MANIFEST_INVALID:'图片清单需要核对',ASSET_RECORD_MISSING:'素材记录缺失',ASSET_MISSING:'本机文件缺失',ASSET_UNREADABLE:'本机文件暂时无法读取',ROOT_UNKNOWN:'素材原保存位置未知',IMAGE_FORMAT_UNKNOWN:'图片格式尚不能确认',ASSET_STATE_UNKNOWN:'素材校验状态尚不能确认',SIZE_MISMATCH:'文件大小与记录不一致',HASH_MISMATCH:'文件内容与记录不一致',SOURCE_CHANGED:'检查期间文件发生变化',IMAGE_INVALID:'图片无法正常解码',BACKUP_UNAVAILABLE:'备份缺失或未通过完整性校验',DISK_RESERVE:'可用空间不足',OUTPUT_WRITE_FAILED:'无法写入备份目录',STAGING_LIMIT:'多次中断留下暂存文件，需要检查维护目录'};
export const issueText=code=>reasons[code]||'此项目需要进一步核对';
export function findingsText(groups=[]){
  const category={missing:'缺失',damaged:'损坏',unknown:'待确认'};
  return groups.map(g=>`${category[g.category]||'需留意'}：${issueText(g.code)} · ${g.count} 项${g.product_count?'，涉及 '+g.product_count+' 款':''}${g.product_names?.length?'\n款式：'+g.product_names.join('、')+(g.product_count>g.product_names.length?' 等':''):''}`).join('\n\n');
}
