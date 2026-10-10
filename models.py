"""
小黑盒数据模型
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ==================== 帖子相关模型 ====================


class Emoji(BaseModel):
    """表情信息"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="表情名称")
    emoji_id: str = Field(..., description="表情ID")
    sprite_url: str = Field(..., description="雪碧图URL")
    background_position: str = Field(default="", description="背景位置")


class Medal(BaseModel):
    """勋章信息"""

    model_config = ConfigDict(extra="ignore")

    medal_id: int = Field(default=0, description="勋章ID")
    name: str = Field(default="", description="勋章名称")
    description: str = Field(default="", description="勋章描述")
    img_url: str = Field(default="", description="勋章图标URL")
    level: int = Field(default=0, description="勋章等级")
    achieved: int = Field(default=0, description="是否已获得")
    wear: int = Field(default=0, description="是否佩戴")


class PostAuthor(BaseModel):
    """帖子作者信息"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="未知用户", description="作者名称")
    level: str = Field(default="", description="用户等级")
    avatar_url: Optional[str] = Field(None, description="头像URL")
    user_id: Optional[str] = Field(None, description="用户ID")
    medals: List[Medal] = Field(default_factory=list, description="用户勋章列表")
    wearing_medal: Optional[Medal] = Field(None, description="当前佩戴的勋章")


class PostStats(BaseModel):
    """帖子统计信息"""

    model_config = ConfigDict(extra="ignore")

    views: int = Field(default=0, description="观看数")
    likes: int = Field(default=0, description="点赞数")
    favorites: int = Field(default=0, description="收藏数")
    comments: int = Field(default=0, description="评论数")


class PostImage(BaseModel):
    """帖子图片信息"""

    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., description="图片URL")
    local_path: Optional[str] = Field(None, description="本地保存路径")


class PostVideo(BaseModel):
    """帖子视频信息"""

    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., description="视频URL")
    poster: Optional[str] = Field(None, description="视频封面图URL")
    width: Optional[int] = Field(None, description="视频宽度")
    height: Optional[int] = Field(None, description="视频高度")
    duration: Optional[float] = Field(None, description="视频时长（秒）")


class CommentImage(BaseModel):
    """评论图片信息"""

    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., description="图片URL")
    thumb: Optional[str] = Field(None, description="缩略图URL")
    width: Optional[int] = Field(None, description="图片宽度")
    height: Optional[int] = Field(None, description="图片高度")
    local_path: Optional[str] = Field(None, description="本地保存路径")


class CommentUser(BaseModel):
    """评论用户信息"""

    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(default="", description="用户ID")
    name: str = Field(default="匿名用户", description="用户名称")
    level: str = Field(default="", description="用户等级")
    avatar_url: Optional[str] = Field(None, description="头像URL")
    medals: List[Medal] = Field(default_factory=list, description="用户勋章列表")
    wearing_medal: Optional[Medal] = Field(None, description="当前佩戴的勋章")


class Comment(BaseModel):
    """评论信息"""

    model_config = ConfigDict(extra="ignore")

    comment_id: str = Field(default="", description="评论ID")
    author: CommentUser = Field(default_factory=CommentUser, description="评论作者")
    content: str = Field(default="", description="评论内容")
    emojis: List[Emoji] = Field(default_factory=list, description="评论中的表情")
    time: str = Field(default="", description="评论时间")
    location: str = Field(default="", description="评论地点")
    likes: int = Field(default=0, description="点赞数")
    floor_num: int = Field(default=0, description="楼层号")
    images: List[CommentImage] = Field(default_factory=list, description="评论图片")
    reply_to: Optional[CommentUser] = Field(None, description="回复的用户")
    child_comments: List["Comment"] = Field(default_factory=list, description="子评论")
    is_top: int = Field(default=0, description="是否置顶")
    has_more: int = Field(default=0, description="是否有更多子评论")
    child_num: int = Field(default=0, description="子评论总数")


class Post(BaseModel):
    """小黑盒帖子完整信息"""

    model_config = ConfigDict(
        extra="ignore",
        json_encoders={datetime: lambda v: v.isoformat()},
    )

    post_id: str = Field(default="", description="帖子ID")
    url: str = Field(default="", description="帖子URL")
    title: str = Field(default="", description="帖子标题")
    content: str = Field(default="", description="帖子正文内容")
    description: str = Field(default="", description="帖子摘要")
    author: PostAuthor = Field(default_factory=PostAuthor, description="作者信息")
    tags: List[str] = Field(default_factory=list, description="帖子标签")
    images: List[PostImage] = Field(default_factory=list, description="帖子图片")
    video: Optional[PostVideo] = Field(None, description="帖子视频")
    stats: PostStats = Field(default_factory=PostStats, description="统计信息")
    time: str = Field(default="", description="发布时间（相对格式如'1天前'）")
    create_at: Optional[int] = Field(None, description="发布时间（Unix时间戳）")
    location: str = Field(default="", description="发布地点")
    comments: List[Comment] = Field(default_factory=list, description="评论列表")
    crawled_at: datetime = Field(default_factory=datetime.now, description="爬取时间")


# ==================== 创作者后台模型 ====================


class FlowSource(BaseModel):
    """流量来源"""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(default="", description="来源名称")
    value: int = Field(default=0, description="占比（百分比）")


class DailyTrend(BaseModel):
    """每日趋势数据"""

    model_config = ConfigDict(extra="ignore")

    timestamp: int = Field(default=0, description="日期时间戳")
    click: int = Field(default=0, description="浏览量")
    comment: int = Field(default=0, description="评论数")
    share: int = Field(default=0, description="分享数")
    favour: int = Field(default=0, description="收藏数")
    award: int = Field(default=0, description="点赞/充电数")
    battery: int = Field(default=0, description="充电量")
    follow: int = Field(default=0, description="关注数")
    new_follow: int = Field(default=0, description="新增粉丝")
    lost_follow: int = Field(default=0, description="取关数")
    avg_time: int = Field(default=0, description="平均阅读时长（秒）")


class CreatorArticleData(BaseModel):
    """创作者文章详情数据"""

    model_config = ConfigDict(extra="ignore")

    link_id: int = Field(default=0, description="帖子ID")
    title: str = Field(default="", description="标题")
    click: int = Field(default=0, description="精确浏览量")
    exposure_count: int = Field(default=0, description="曝光量")
    raw_view_time_count: int = Field(default=0, description="有效阅读数(原始)")
    view_time_count: int = Field(default=0, description="有效阅读数")
    avg_time: int = Field(default=0, description="平均阅读时长(秒)")
    new_follow: int = Field(default=0, description="新增粉丝")
    share_url: str = Field(default="", description="分享链接")
    has_video: int = Field(default=0, description="是否有视频")
    create_at: int = Field(default=0, description="发布时间戳")
    article_desc: str = Field(default="", description="文章类型描述")
    imgs: List[str] = Field(default_factory=list, description="封面图列表")
    thumbs: List[str] = Field(default_factory=list, description="缩略图列表")
    flow_source_info: List[FlowSource] = Field(default_factory=list, description="流量来源分布")
    statistic_data: dict = Field(default_factory=dict, description="详细统计数据")


class CreatorStats(BaseModel):
    """创作者数据汇总（文章详情 + 日趋势）"""

    model_config = ConfigDict(extra="ignore")

    article: CreatorArticleData = Field(default_factory=CreatorArticleData, description="文章详情")
    data_trends: List[DailyTrend] = Field(default_factory=list, description="每日数据趋势")


class CreatorListItem(BaseModel):
    """创作者文章列表中的单条文章"""

    model_config = ConfigDict(extra="ignore")

    link_id: int = Field(default=0, description="帖子ID")
    title: str = Field(default="", description="标题")
    link_type: Optional[Union[str, int]] = Field(default=None, description="内容类型")
    click: int = Field(default=0, description="浏览量")
    thumbs: int = Field(default=0, description="点赞数")
    comment: int = Field(default=0, description="评论数")
    create_at: int = Field(default=0, description="发布时间戳")
    raw_view_time_count: int = Field(default=0, description="有效阅读数")
    new_follow: int = Field(default=0, description="新增粉丝")
    share_url: str = Field(default="", description="分享链接")
    has_video: int = Field(default=0, description="是否有视频 0/1")
    link_tag: Optional[Union[str, int]] = Field(default=None, description="标签")
    article_desc: str = Field(default="", description="文章类型描述")
    award: int = Field(default=0, description="奖励/充电数")
    imgs: List[str] = Field(default_factory=list, description="封面图列表")


class CreatorArticleList(BaseModel):
    """创作者已发布文章列表"""

    model_config = ConfigDict(extra="ignore")

    articles: List[CreatorListItem] = Field(default_factory=list, description="文章列表")
    total: int = Field(default=0, description="总数量")
    sort_filters: List[str] = Field(default_factory=list, description="排序选项")
    state_filters: List[str] = Field(default_factory=list, description="状态筛选")


# ==================== 发布接口模型 ====================


class PublishResult(BaseModel):
    """发布/草稿保存结果"""

    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=False, description="是否成功")
    link_id: Optional[Union[str, int]] = Field(None, description="文章ID（成功时）")
    message: str = Field(default="", description="API 返回消息")
    is_draft: bool = Field(default=True, description="是否为草稿")
    raw: dict = Field(default_factory=dict, description="原始 API 响应")
